from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from onyx.configs.constants import DocumentSource
from onyx.connectors.factory import instantiate_connector
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.db.models import Connector, ConnectorCredentialPair


@dataclass(frozen=True)
class RedminePermissionTarget:
    connector_id: int
    credential_id: int
    connector: SlimConnectorWithPermSync


def redmine_sync_connectors() -> list[RedminePermissionTarget]:
    with get_session_with_current_tenant() as db_session:
        statement = (
            select(ConnectorCredentialPair)
            .join(Connector)
            .where(
                Connector.source == DocumentSource.REDMINE,
                ConnectorCredentialPair.access_type == AccessType.SYNC,
                ConnectorCredentialPair.status == ConnectorCredentialPairStatus.ACTIVE,
            )
            .options(
                joinedload(ConnectorCredentialPair.connector),
                joinedload(ConnectorCredentialPair.credential),
            )
        )
        pairs = list(db_session.scalars(statement).unique().all())
        connectors: list[RedminePermissionTarget] = []
        for pair in pairs:
            connector = instantiate_connector(
                db_session=db_session,
                source=pair.connector.source,
                input_type=pair.connector.input_type,
                connector_specific_config=pair.connector.connector_specific_config,
                credential=pair.credential,
            )
            if not isinstance(connector, SlimConnectorWithPermSync):
                raise RuntimeError("Redmine connector cannot reconcile permissions")
            connectors.append(
                RedminePermissionTarget(
                    connector_id=pair.connector_id,
                    credential_id=pair.credential_id,
                    connector=connector,
                )
            )
        return connectors
