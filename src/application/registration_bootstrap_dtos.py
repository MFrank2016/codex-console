"""
Web/Application 边界上的注册 bootstrap 阶段 DTO。

这些 DTO 仅用于启动阶段快照/结果传递，刻意不承载运行态字段
（如 logs、proxy_ip、steps）。Batch/Outlook 的集合字段会规范化为 tuple，
以表达只读、可共享（share-safe）的语义。
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RegistrationTaskSnapshot:
    id: int
    task_uuid: str
    status: str
    proxy: str | None = None
    pipeline_key: str | None = None
    email_service_id: int | None = None


@dataclass(frozen=True)
class BatchBootstrapResult:
    batch_id: str
    task_snapshots: tuple[RegistrationTaskSnapshot, ...] = field(default_factory=tuple)
    is_unlimited: bool = False

    def __post_init__(self):
        object.__setattr__(self, "task_snapshots", tuple(self.task_snapshots))


@dataclass(frozen=True)
class OutlookBatchBootstrapResult:
    batch_id: str
    total: int
    skipped: int
    service_ids: tuple[int, ...] = field(default_factory=tuple)

    def __post_init__(self):
        object.__setattr__(self, "service_ids", tuple(self.service_ids))
