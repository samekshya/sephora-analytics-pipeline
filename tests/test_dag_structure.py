"""
test_dag_structure.py
---------------------
Structural assertions about the Airflow DAG.

These do not run the pipeline. They prove the DAG is wired the way the design
claims — most importantly that cleanup_staging is a teardown and therefore
cannot report success on a failed run's behalf. That property is easy to break
(marking cleanup as an ordinary task, or passing on_failure_fail_dagrun=True),
and the failure mode is invisible: the DAG keeps working, and silently stops
reporting failures.

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
}

# The staging-writing branches. cleanup must wait for all of them, not just the
# fact chain — see test_cleanup_waits_for_every_staging_writer.
STAGING_WRITER_LOADS = {
  "load_product_from_staging",
  "load_customer_from_staging",
  "load_reviewer_profile_from_staging",
  "load_fact_from_staging",
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
# The cleanup teardown — the reason this file exists
# --------------------------------------------------------------------------

def _is_effective_leaf(dag, task):
  """Reimplements Airflow's DagRun._tis_for_dagrun_state leaf rule.

  A task counts toward DAG run state only if every downstream is an ignorable
  teardown and it is not itself one. Copied deliberately rather than imported:
  these tests must fail loudly if Airflow ever changes the rule under us.
  """
  for down_id in task.downstream_task_ids:
    down = dag.get_task(down_id)
    if not down.is_teardown or down.on_failure_fail_dagrun:
      return False
  return not task.is_teardown or task.on_failure_fail_dagrun


def test_cleanup_runs_even_after_failure(dag):
  """Teardown trigger rules fire once upstreams are done, failed included."""
  assert _rule(dag.get_task("cleanup_staging")).startswith("all_done")


def test_cleanup_is_a_teardown(dag):
  assert dag.get_task("cleanup_staging").is_teardown


def test_cleanup_cannot_speak_for_the_run(dag):
  """THE critical assertion.

  Airflow derives a DAG run's state from its leaf tasks. cleanup_staging runs
  even when an upstream failed — as an ordinary task it would be the only leaf,
  and its success would report SUCCESS over a run that loaded nothing. Marking
  it a teardown removes it from that calculation.
  """
  leaves = {t.task_id for t in dag.tasks if _is_effective_leaf(dag, t)}
  assert leaves == {"load_fact_from_staging"}, (
    f"effective leaves are {leaves}; cleanup_staging must not be among them")


def test_cleanup_does_not_fail_the_dagrun(dag):
  """on_failure_fail_dagrun MUST stay False.

  Setting it True to make cleanup's own failure count would make cleanup
  non-ignorable, which makes it the sole effective leaf again — reinstating
  exactly the bug this design exists to prevent.
  """
  assert dag.get_task("cleanup_staging").on_failure_fail_dagrun is False


def test_every_task_can_fail_the_run(dag):
  """Any task's failure must reach the effective leaf, or it is invisible.

  Replaces the old 'watcher watches everything' assertion: propagation through
  upstream_failed does the job the watcher's 15 edges used to do.
  """
  def reaches_leaf(task_id, seen=None):
    seen = seen if seen is not None else set()
    if task_id == "load_fact_from_staging":
      return True
    if task_id in seen:
      return False
    seen.add(task_id)
    return any(reaches_leaf(d, seen)
               for d in dag.get_task(task_id).downstream_task_ids)

  unwatched = {t.task_id for t in dag.tasks
               if t.task_id not in ("load_fact_from_staging", "cleanup_staging")
               and not reaches_leaf(t.task_id)}
  assert not unwatched, f"failures invisible to DAG state: {unwatched}"


def test_cleanup_waits_for_every_staging_writer(dag):
  """Regression test for a race found by failure injection.

  With load_fact as cleanup's only upstream, a fact chain that short-circuits
  to upstream_failed let cleanup run while the dimension branches were still
  staging — it deleted nothing and stranded 513,606 rows carrying that run's
  own batch_id.
  """
  assert dag.get_task("cleanup_staging").upstream_task_ids == STAGING_WRITER_LOADS


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
