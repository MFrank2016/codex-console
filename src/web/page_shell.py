"""Shared workspace shell context helpers."""

WORKSPACE_NAV = [
    {
        "group": "总览",
        "items": [
            {"key": "dashboard", "label": "控制台总览", "href": "/"},
        ],
    },
    {
        "group": "执行",
        "items": [
            {
                "key": "registration_workbench",
                "label": "注册工作台",
                "href": "/registration-workbench",
            },
            {
                "key": "scheduled_tasks",
                "label": "定时任务",
                "href": "/scheduled-tasks",
            },
        ],
    },
    {
        "group": "复盘",
        "items": [
            {"key": "accounts", "label": "账号管理", "href": "/accounts"},
            {
                "key": "registration_experiments",
                "label": "注册实验",
                "href": "/registration-experiments",
            },
        ],
    },
    {
        "group": "配置",
        "items": [
            {"key": "settings", "label": "系统设置", "href": "/settings"},
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
