import logging

from .services.mlflow_client import (
    MlflowClientError,
    delete_all_experiment_tags,
    delete_artifacts_from_object_storage,
    delete_experiment,
    delete_mlflow_user,
    find_any_run_id,
    make_deleted_experiment_name,
    purge_deleted_experiment,
    update_experiment_name,
)

logger = logging.getLogger(__name__)

# find_any_run_id couldn't tell
UNKNOWN = object()


def discard_mlflow_experiment(*, mlflow_experiment_id):
    """Best-effort removal of a deleted experiment from MLflow (queued by
    projects/signals.py), in the same steps as the experiment delete view: the
    artifacts in object storage, then a rename that frees the name, then the
    delete. MLflow's delete is a soft delete, so the experiment and its runs,
    params and metrics are then purged from its trash. Failures are logged with
    the id, for a manual clean-up, rather than raised. Runs on the qcluster, with
    the MLflow service credentials."""
    try:
        delete_artifacts_from_object_storage(mlflow_experiment_id)
    except MlflowClientError:
        logger.exception("Could not delete artifacts of MLflow experiment %s; they are orphaned", mlflow_experiment_id)

    try:
        # Before the delete, while the experiment is still active
        run_id = find_any_run_id(mlflow_experiment_id)
    except MlflowClientError:
        logger.exception("Could not look up the runs of MLflow experiment %s; it won't be purged", mlflow_experiment_id)
        run_id = UNKNOWN

    if run_id is None:
        # Without a run the trash cleanup can't be narrowed to this experiment
        # (see purge_deleted_experiment), so it stays in the trash: empty its tags
        # (the project name, the description) first.
        try:
            delete_all_experiment_tags(mlflow_experiment_id)
        except MlflowClientError:
            logger.exception("Could not delete the tags of MLflow experiment %s", mlflow_experiment_id)

    try:
        update_experiment_name(mlflow_experiment_id, make_deleted_experiment_name())
        delete_experiment(mlflow_experiment_id)
    except MlflowClientError:
        logger.exception("Could not delete MLflow experiment %s; it is orphaned", mlflow_experiment_id)
        return

    if run_id is None:
        logger.warning("MLflow experiment %s has no runs; left in the MLflow trash", mlflow_experiment_id)
        return
    if run_id is UNKNOWN:
        return
    try:
        purge_deleted_experiment(mlflow_experiment_id, run_id)
    except MlflowClientError:
        logger.exception("Could not purge MLflow experiment %s from the trash", mlflow_experiment_id)


def discard_mlflow_user(*, username):
    """Best-effort removal of a deleted account's MLflow-OIDC user (queued by
    projects/signals.py). Failures are logged rather than raised."""
    try:
        delete_mlflow_user(username)
    except MlflowClientError:
        logger.exception("Could not delete MLflow user %s; it is orphaned", username)
