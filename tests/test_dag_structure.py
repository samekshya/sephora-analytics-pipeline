"""
test_dag_structure.py
---------------------
Structural assertions about the Airflow DAG.

These do not run the pipeline. They prove the DAG is wired the way the design
claims — most importantly that the failure watcher is present, is the only
leaf, and watches everything. That property is easy to break by adding a task
and forgetting to wire it to the watcher, and the failure mode is invisible:
the DAG keeps working, and silently stops reporting failures.

Skipped when airflow isn't importable (it lives in the container, not
necessarily in the local venv):

  docker exec leapfrog_airflow_scheduler python -m pytest /opt/airflow/tests/test_dag_structure.py
"""

import pytest

pytestmark = pytest.mark.dag

pytest.importorskip("airflow", reason="apache-airflow not installed locally")

import os  # noqa: E402

DAG_ID = "sephora_dw_pipeline_staged"

EXPECTED_TASKS = {
  "create_staging_tables",
  "extract_brand_to_staging", "load_brand_from_staging",
  "extract_customer_to_staging", "load_customer_from_staging",
  "extract_reviewer_profile_to_staging", "load_reviewer_profile_from_staging",
  "extract_product_to_staging", "load_product_from_staging",
  "load_date_dimension",
  "extract_fact_to_staging", "transform_fact_staged",
  "quality_check_fact_staged", "load_fact_from_staging",
  "cleanup_staging",
  "watch_for_failure",
}


def _rule(task):
  """Trigger rule as a plain string.

  In Airflow 3 TriggerRule is an enum whose str() is 'TriggerRule.ONE_FAILED';
  in Airflow 2 it was a str subclass giving 'one_failed'. .value is the stable
  form across both.
  """
  return getattr(task.trigger_rule, "value", str(task.trigger_rule))


@pytest.fixture(scope="module")
def dag():
  from airflow.models import DagBag

  dags_folder = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dags")
  bag = DagBag(dags_folder)

  assert not bag.import_errors, f"DAG import errors: {bag.import_errors}"

  loaded = bag.dags.get(DAG_ID)
  assert loaded is not None, f"{DAG_ID} not found in {sorted(bag.dags)}"
  return loaded


def test_dag_imports_without_errors(dag):
  assert dag.dag_id == DAG_ID


def test_expected_tasks_present(dag):
  actual = {t.task_id for t in dag.tasks}
  assert actual == EXPECTED_TASKS, (
    f"missing: {EXPECTED_TASKS - actual}, unexpected: {actual - EXPECTED_TASKS}")


def test_retry_policy(dag):
  extract = dag.get_task("extract_fact_to_staging")
  assert extract.retries == 2
  assert extract.retry_delay.total_seconds() == 300


def test_load_mode_param_offers_three_modes(dag):
  param = dag.params.get_param("load_mode")
  assert param.schema.get("enum") == ["full", "historical", "incremental"]
  assert param.value == "incremental", "default must be the safe, cheap mode"


# --------------------------------------------------------------------------
# The cleanup / watcher interaction — the reason this file exists
# --------------------------------------------------------------------------

def test_cleanup_runs_even_after_failure(dag):
  """all_done, so a failed run still cleans up its staging rows."""
  assert _rule(dag.get_task("cleanup_staging")) == "all_done"


def test_watcher_uses_one_failed(dag):
  assert _rule(dag.get_task("watch_for_failure")) == "one_failed"


def test_watcher_does_not_retry(dag):
  """Retrying a task whose only job is reporting an existing failure would
  just delay the red status."""
  assert dag.get_task("watch_for_failure").retries == 0


def test_watcher_is_the_only_leaf(dag):
  """THE critical assertion.

  Airflow derives a DAG run's state from its leaf tasks. cleanup_staging runs
  with all_done so it succeeds even when an upstream task failed — if it were
  a leaf, a failed run would report SUCCESS. The watcher must be the only leaf
  for DAG state to reflect failure.
  """
  leaves = {t.task_id for t in dag.tasks if not t.downstream_task_ids}
  assert leaves == {"watch_for_failure"}, (
    f"leaves are {leaves}; any leaf other than the watcher can mask a failure")


def test_watcher_watches_every_other_task(dag):
  """trigger_rule evaluates DIRECT upstreams only, so a task missing from the
  watcher's upstream set is a failure the watcher cannot see."""
  watcher = dag.get_task("watch_for_failure")
  everything_else = {t.task_id for t in dag.tasks} - {"watch_for_failure"}

  assert watcher.upstream_task_ids == everything_else, (
    f"not watched: {everything_else - watcher.upstream_task_ids}")


def test_cleanup_precedes_watcher(dag):
  """Cleanup must have run before the watcher fails the run, or a failed run
  could leave staging rows behind."""
  assert "watch_for_failure" in dag.get_task("cleanup_staging").downstream_task_ids


# --------------------------------------------------------------------------
# Fact stages are separately retryable
# --------------------------------------------------------------------------

def test_fact_is_split_into_four_stages(dag):
  chain = ["extract_fact_to_staging", "transform_fact_staged",
           "quality_check_fact_staged", "load_fact_from_staging"]

  for upstream, downstream in zip(chain, chain[1:]):
    assert downstream in dag.get_task(upstream).downstream_task_ids, (
      f"{upstream} should feed {downstream}")


def test_product_waits_for_brand(dag):
  """dim_product resolves brand_key, so dim_brand must be loaded first."""
  brand_load = dag.get_task("load_brand_from_staging")
  assert "extract_product_to_staging" in brand_load.downstream_task_ids
