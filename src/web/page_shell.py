"""Shared workspace shell context helpers."""

WORKSPACE_NAV = [
    {
        "group": "总览",
        "items": [
            {
                "key": "dashboard",
                "label": "控制台总览",
                "href": "/",
                "icon": "dashboard",
            },
        ],
    },
    {
        "group": "执行",
        "items": [
            {
                "key": "registration_workbench",
                "label": "注册工作台",
                "href": "/registration-workbench",
                "icon": "registration_workbench",
            },
            {
                "key": "run_center",
                "label": "运行中心",
                "href": "/run-center",
                "icon": "run_center",
            },
            {
                "key": "accounts",
                "label": "账号管理",
                "href": "/accounts",
                "icon": "accounts",
            },
        ],
    },
    {
        "group": "复盘",
        "items": [
            {
                "key": "registration_experiments",
                "label": "注册实验",
                "href": "/registration-experiments",
                "icon": "registration_experiments",
            },
            {
                "key": "registration_batch_stats",
                "label": "批次统计",
                "href": "/registration-batch-stats",
                "icon": "registration_batch_stats",
            },
        ],
    },
    {
        "group": "支撑",
        "items": [
            {
                "key": "scheduled_tasks",
                "label": "定时任务",
                "href": "/scheduled-tasks",
                "icon": "scheduled_tasks",
            },
            {
                "key": "email_services",
                "label": "邮箱服务",
                "href": "/email-services",
                "icon": "email_services",
            },
            {
                "key": "settings",
                "label": "系统设置",
                "href": "/settings",
                "icon": "settings",
            },
            {"key": "payment", "label": "支付中心", "href": "/payment", "icon": "payment"},
        ],
    },
]


def build_page_shell(*, page_key: str, page_title: str, page_subtitle: str) -> dict[str, object]:
    """Build shared template context for pages that participate in the workspace shell."""
    return {
        "page_key": page_key,
        "page_title": page_title,
        "page_subtitle": page_subtitle,
        "workspace_nav": WORKSPACE_NAV,
    }
