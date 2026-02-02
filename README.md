# PM Dashboard - GitHub Issue Monitor

自动监控 GitHub Projects 中的 Issue 状态，生成可视化 Dashboard。

## 功能

- 每天自动更新 Issue 数据
- 按优先级 (P0/P1/P2) 分类展示
- 按截止日期预警 (已逾期、7天内)
- 按客户/标签筛选
- 按负责人分类
- 风险评分系统

## 部署步骤

### 1. 创建 GitHub 仓库

```bash
# 在 GitHub 上创建新仓库，如 sparticleinc/issue-dashboard
# 然后推送本地代码
cd issue-dashboard
git init
git add .
git commit -m "Initial commit"
git remote add origin git@github.com:sparticleinc/issue-dashboard.git
git push -u origin main
```

### 2. 配置 GitHub Token

1. 进入仓库 Settings > Secrets and variables > Actions
2. 点击 "New repository secret"
3. Name: `GH_PAT`
4. Value: 你的 GitHub Personal Access Token（需要 `repo` 和 `read:project` 权限）

### 3. 连接 Netlify

1. 登录 [Netlify](https://app.netlify.com)
2. 点击 "Add new site" > "Import an existing project"
3. 选择 GitHub，授权访问
4. 选择 `issue-dashboard` 仓库
5. 配置：
   - Branch: `main`
   - Publish directory: `public`
   - Build command: 留空
6. 点击 "Deploy site"

### 4. 自定义域名（可选）

1. 在 Netlify Site settings > Domain management
2. 添加自定义域名，如 `issue-dashboard.yourcompany.com`
3. 配置 DNS 记录

## 手动触发更新

在 GitHub 仓库的 Actions 页面，选择 "Update PM Dashboard" workflow，点击 "Run workflow"。

## 本地开发

```bash
# 设置环境变量
export GITHUB_TOKEN="your_token_here"

# 运行生成脚本
python scripts/generate_dashboard.py

# 查看结果
open public/index.html
```

## 文件结构

```
issue-dashboard/
├── .github/
│   └── workflows/
│       └── update-dashboard.yml  # GitHub Actions 定时任务
├── scripts/
│   └── generate_dashboard.py     # 数据获取和 HTML 生成脚本
├── public/
│   └── index.html               # 生成的 Dashboard (自动更新)
├── netlify.toml                 # Netlify 配置
└── README.md
```

## 配置说明

### 修改监控的项目

编辑 `scripts/generate_dashboard.py` 中的 `PROJECTS` 列表：

```python
PROJECTS = [
    ("PVT_kwDOBO9uks4BDgXM", "项目名称1"),
    ("PVT_kwDOBO9uks4BHLOl", "项目名称2"),
    # 添加更多项目...
]
```

### 修改定时执行时间

编辑 `.github/workflows/update-dashboard.yml` 中的 cron 表达式：

```yaml
schedule:
  - cron: '0 1 * * *'  # UTC 01:00 = 北京时间 09:00
```

## License

MIT
