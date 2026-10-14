"""Запуск локального приложения."""

import os

import uvicorn

from .api import create_app


if __name__ == '__main__':
    uvicorn.run(create_app(), host=os.environ.get('HR_HOST', '127.0.0.1'), port=int(os.environ.get('HR_PORT', '8000')))
