#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""启动本地 HTTP 服务，供刷题页面加载 JSON 与公式图片。"""

import http.server
import socketserver
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8765


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)


def main() -> None:
    url = f"http://127.0.0.1:{PORT}/app/index.html"
    with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
        print(f"服务已启动: {url}")
        print("按 Ctrl+C 停止")
        webbrowser.open(url)
        httpd.serve_forever()


if __name__ == "__main__":
    main()
