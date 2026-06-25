# 自动控制原理 · 刷题背题工具

从 PDF 解析 100 道选择题，在网页中刷题/背题。支持本地运行，也可部署到 **Gitee Pages** 供多人通过链接访问。

## 快速开始（本地）

### 1. 解析 PDF（首次或 PDF 更新后）

```bash
python scripts/parse_pdf.py
```

生成：
- `data/questions.json` — 结构化题库
- `data/formulas/*.png` — 公式截图（教材原样）

### 2. 打开刷题页面

```bash
python scripts/serve.py
```

浏览器会自动打开 `http://127.0.0.1:8765/app/index.html`。

> 不要直接用文件协议打开 HTML，否则无法加载 JSON 和图片。

---

## 部署到 Gitee Pages（多人使用，推荐）

无需内网穿透、无需打包 APK，部署后分享一个链接即可。

### 一次性准备

1. 在 [Gitee](https://gitee.com) 新建仓库（可设为**公开**，Pages 免费版需公开库）
2. 在本项目目录初始化并推送代码：

```bash
git init
git add .
git commit -m "init: 自控刷题工具"
git remote add origin https://gitee.com/<你的用户名>/<仓库名>.git
git push -u origin master
```

> 若默认分支是 `main`，把上面命令里的 `master` 换成 `main`。

### 每次更新题库或页面后

```bash
# 1. 若 PDF 有变，重新解析
python scripts/parse_pdf.py

# 2. 生成 Gitee Pages 静态站（输出到 docs/）
python scripts/deploy_gitee.py

# 3. 提交并推送
git add .
git commit -m "deploy: 更新刷题站"
git push
```

### 开启 Pages

1. 打开 Gitee 仓库 → **服务** → **Gitee Pages**
2. **部署分支**：`master` 或 `main`
3. **部署目录**：`/docs`
4. 点击 **启动** / **更新**

部署成功后访问：

```text
https://<你的用户名>.gitee.io/<仓库名>/
```

把该链接发给同学即可；每人浏览器打开就能刷题，错题本保存在各自浏览器本地。

### 注意

- 首次推送含大量公式图片，`git push` 可能较慢，属正常现象
- 免费 Pages 长时间无访问可能休眠，再次打开链接时会自动恢复
- 修改 PDF 后务必重新执行 `parse_pdf.py` 和 `deploy_gitee.py` 再推送

---

## 功能

| 功能 | 说明 |
|------|------|
| 背题模式 | 选题后立即显示对错与正确答案 |
| 考试模式 | 全部做完后交卷，统一出成绩 |
| 顺序 / 乱序 | 按题号或随机顺序 |
| 错题本 | 做错的题自动记录，可「仅刷错题」 |
| 公式显示 | MathJax 渲染符号 + PDF 原公式截图（点击可放大） |
| 快捷键 | 选题后按空格或右键进入下一题 |

## 目录结构

```
自控/
├── 自动控制原理选择题（100题）.pdf
├── scripts/
│   ├── parse_pdf.py      # PDF → JSON
│   ├── deploy_gitee.py   # 生成 docs/ 供 Gitee Pages
│   └── serve.py          # 本地调试
├── data/                 # 题库数据（解析产物）
├── app/                  # 前端源码（本地 serve 用）
├── docs/                 # Gitee Pages 部署目录（deploy 生成，需提交）
└── README.md
```

## 手动修正

若个别题目文字或公式不理想，可直接编辑 `data/questions.json`，然后重新运行 `deploy_gitee.py` 并推送。
