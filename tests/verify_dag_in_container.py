"""
verify_dag_in_container.py
--------------------------
The same structural assertions as tests/test_dag_structure.py, written to run
with PLAIN PYTHON inside the Airflow container.

Why both exist: test_dag_structure.py needs pytest, which is not installed in
the apache/airflow image and cannot be pip-installed into it without root. But
the assertions are worthless where airflow ISN'T importable, which is the host
venv - so the pytest version skips exactly where it matters most. This file
closes that gap, using nothing but the standard library and airflow itself.

    docker exec leapfrog_airflow_scheduler python \
        /opt/airflow/dags/../project/tests/verify_dag_in_container.py

If tests/ is not mounted yet (it is added to docker-compose-airflow.yml but
takes effect on the next `docker compose up`), copy it in first:

    docker cp tests/verify_dag_in_container.py leapfrog_airflow_scheduler:/tmp/
    docker exec leapfrog_airflow_scheduler python /tmp/verify_dag_in_container.py

Exit code 0 = every assertion passed. Non-zero = something is wired wrong.
"""

import sys

from airflow.models import DagBag

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

STAGING_WRITER_LOADS = {
    "load_product_from_staging",
    "load_customer_from_staging",
    "load_reviewer_profile_from_staging",
    "load_fact_from_staging",
}

passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"PASS  {name}" + (f"  ({detail})" if detail else ""))
    else:
        failed += 1
        print(f"FAIL  {name}  {detail}")


def rule(task):
    """Airflow 3 TriggerRule is an enum; .value is stable across 2 and 3."""
    return getattr(task.trigger_rule, "value", str(task.trigger_rule))


def main():
    bag = DagBag("/opt/airflow/dags")
    if bag.import_errors:
        print("FAIL  dag imports without errors")
        for path, err in bag.import_errors.items():
            print(f"      {path}: {err}")
        return 1
    print("PASS  dag imports without errors")

    dag = bag.dags.get(DAG_ID)
    if dag is None:
        print(f"FAIL  {DAG_ID} not found in {sorted(bag.dags)}")
        return 1

    actual = {t.task_id for t in dag.tasks}
    check("expected_tasks_present", actual == EXPECTED_TASKS,
          f"{len(actual)} tasks; missing={EXPECTED_TASKS - actual}, "
          f"unexpected={actual - EXPECTED_TASKS}")

    cleanup = dag.get_task("cleanup_staging")
    check("cleanup_runs_even_after_failure", rule(cleanup).startswith("all_done"),
          rule(cleanup))
    check("cleanup_is_a_teardown", cleanup.is_teardown)
    check("cleanup_does_not_fail_the_dagrun",
          cleanup.on_failure_fail_dagrun is False,
          "True would make cleanup the sole effective leaf again")

    def is_effective_leaf(task):
        """Mirrors Airflow's DagRun._tis_for_dagrun_state leaf rule."""
        for down_id in task.downstream_task_ids:
            down = dag.get_task(down_id)
            if not down.is_teardown or down.on_failure_fail_dagrun:
                return False
        return not task.is_teardown or task.on_failure_fail_dagrun

    leaves = {t.task_id for t in dag.tasks if is_effective_leaf(t)}
    check("cleanup_cannot_speak_for_the_run",
          leaves == {"load_fact_from_staging"}, str(leaves))

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
    check("every_task_can_fail_the_run", not unwatched, str(unwatched))

    check("cleanup_waits_for_every_staging_writer",
          cleanup.upstream_task_ids == STAGING_WRITER_LOADS,
          f"{len(cleanup.upstream_task_ids)} upstreams")

    extract = dag.get_task("extract_fact_to_staging")
    check("retry_policy",
          extract.retries == 2 and extract.retry_delay.total_seconds() == 300,
          f"retries={extract.retries}, delay={extract.retry_delay}")

    param = dag.params.get_param("load_mode")
    check("load_mode_param_offers_two_triggerable_modes",
          param.schema.get("enum") == ["full", "incremental"]
          and param.value == "incremental",
          f"default={param.value}, enum={param.schema.get('enum')}")

    chain = ["extract_fact_to_staging", "transform_fact_staged",
             "quality_check_fact_staged", "load_fact_from_staging"]
    chained = all(down in dag.get_task(up).downstream_task_ids
                  for up, down in zip(chain, chain[1:]))
    check("fact_is_split_into_four_stages", chained)

    check("product_waits_for_brand",
          "extract_product_to_staging"
          in dag.get_task("load_brand_from_staging").downstream_task_ids)

    print()
    print(f"{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
