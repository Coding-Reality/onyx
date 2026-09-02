from onyx.connectors.interfaces import BaseConnector
from onyx.connectors.redmine.connector import RedmineConnector


def validate_perm_sync(connector: BaseConnector) -> None:
    if isinstance(connector, RedmineConnector):
        connector.validate_redmine_permission_sync()
