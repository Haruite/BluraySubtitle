"""Shared network requests for the application update checks."""

from PyQt6.QtCore import QObject, QUrl
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkProxyFactory, QNetworkReply, QNetworkRequest

from src.core.version import APP_VERSION
from src.runtime.windows_update import SERVER_WINDOWS_PACKAGE_URL


SERVER_PACKAGE_METADATA_URL = f"{SERVER_WINDOWS_PACKAGE_URL}.txt"


def update_network_manager(parent: QObject) -> QNetworkAccessManager:
    if not QNetworkProxyFactory.usesSystemConfiguration():
        QNetworkProxyFactory.setUseSystemConfiguration(True)
    return QNetworkAccessManager(parent)


def request_update_info(manager: QNetworkAccessManager, url: str, accept: bytes) -> QNetworkReply:
    request = QNetworkRequest(QUrl(url))
    request.setRawHeader(b"Accept", accept)
    request.setRawHeader(b"Cache-Control", b"no-cache")
    request.setRawHeader(b"User-Agent", f"BluraySubtitle/{APP_VERSION}".encode("ascii"))
    request.setTransferTimeout(15_000)
    return manager.get(request)
