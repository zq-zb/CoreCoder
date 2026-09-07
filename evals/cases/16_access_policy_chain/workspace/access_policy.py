from models import AccessRequest


def can_access(request: AccessRequest) -> bool:
    """判断请求是否有权访问目标资源。"""

    return request.role == "admin"
