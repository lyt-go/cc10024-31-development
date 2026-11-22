"""业务路由汇总：抽取适用集专用路由优先注册，通用模块资源路由兜底。"""
from __future__ import annotations

from app.routers import extract, resource

ROUTERS = [extract, resource]
