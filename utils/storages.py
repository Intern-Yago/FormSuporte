import os
from storages.backends.s3 import S3Storage

# Ambiente
DJANGO_ENV = (os.getenv("DJANGO_ENV") or "dev").strip().lower()
IS_PROD = DJANGO_ENV in ("prod", "production")

# Bucket principal (1 por ambiente)
BUCKET_MAIN = os.getenv("MINIO_BUCKET_MAIN", "eaata-prod" if IS_PROD else "eaata-dev")

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "https://eaatamin.ddns.net")
MINIO_REGION = os.getenv("MINIO_REGION", "us-east-1")

class BaseMinioStorage(S3Storage):
    """
    Storage base para MinIO (S3 compatible)
    """
    bucket_name = BUCKET_MAIN
    endpoint_url = MINIO_ENDPOINT
    region_name = MINIO_REGION

    default_acl = None
    addressing_style = "path"
    querystring_auth = (os.getenv("AWS_QUERYSTRING_AUTH", "0") == "1")


# ✅ Default do sistema atual (ocorrências): tudo vai para eaata-prod/ocorrencias/...
class OcorrenciasStorage(BaseMinioStorage):
    location = "ocorrencias"


# Para quando você quiser separar outros apps por prefixo:
class GarantiasStorage(BaseMinioStorage):
    location = "garantias"

class PedidoStorage(BaseMinioStorage):
    location = "pedido"

class SerialVciStorage(BaseMinioStorage):
    location = "serial-vci"
