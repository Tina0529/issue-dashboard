#!/usr/bin/env python3
"""
PM Dashboard Generator
自动从 GitHub Projects 获取 Issue 数据并生成 HTML 报告
"""

import json
import os
import subprocess
from datetime import datetime
from collections import defaultdict

# 从环境变量获取 Token (GitHub Actions 中配置)
TOKEN = os.environ.get('GITHUB_TOKEN', '')

# 要监控的 GitHub Projects
PROJECTS = [
    ("PVT_kwDOBO9uks4BDgXM", "Support应用&功能"),
    ("PVT_kwDOBO9uks4BHLOl", "Knowledge应用&功能"),
    ("PVT_kwDOBO9uks4BHLSj", "BREAX-NEXT"),
    ("PVT_kwDOBO9uks4BKSLM", "GBaseApp"),
    ("PVT_kwDOBO9uks4BGOWp", "Support产品预研"),
]


def fetch_project_items(project_id, cursor=None):
    """使用 GraphQL API 获取项目 items"""
    after_clause = f', after: "{cursor}"' if cursor else ''

    query = f'''
    query {{
      node(id: "{project_id}") {{
        ... on ProjectV2 {{
          title
          items(first: 100{after_clause}) {{
            pageInfo {{
              hasNextPage
              endCursor
            }}
            nodes {{
              fieldValues(first: 15) {{
                nodes {{
                  ... on ProjectV2ItemFieldTextValue {{
                    text
                    field {{ ... on ProjectV2Field {{ name }} }}
                  }}
                  ... on ProjectV2ItemFieldNumberValue {{
                    number
                    field {{ ... on ProjectV2Field {{ name }} }}
                  }}
                  ... on ProjectV2ItemFieldDateValue {{
                    date
                    field {{ ... on ProjectV2Field {{ name }} }}
                  }}
                  ... on ProjectV2ItemFieldSingleSelectValue {{
                    name
                    field {{ ... on ProjectV2SingleSelectField {{ name }} }}
                  }}
                }}
              }}
              content {{
                ... on Issue {{
                  number
                  title
                  url
                  state
                  createdAt
                  updatedAt
                  labels(first: 10) {{ nodes {{ name }} }}
                  assignees(first: 5) {{ nodes {{ login }} }}
                  repository {{ name }}
                }}
              }}
            }}
          }}
        }}
      }}
    }}
    '''

    cmd = [
        'curl', '-s',
        '-H', f'Authorization: bearer {TOKEN}',
        '-X', 'POST',
        '-H', 'Content-Type: application/json',
        '-d', json.dumps({"query": query}),
        'https://api.github.com/graphql'
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(result.stdout)


def fetch_all_issues():
    """获取所有项目的 Issues"""
    all_items = []

    for project_id, project_name in PROJECTS:
        print(f"Fetching {project_name}...")
        cursor = None
        page = 0

        while True:
            page += 1
            data = fetch_project_items(project_id, cursor)

            if 'errors' in data:
                print(f"  Error: {data['errors']}")
                break

            node = data.get('data', {}).get('node')
            if not node:
                break

            items = node.get('items', {}).get('nodes', [])
            print(f"  Page {page}: {len(items)} items")

            for item in items:
                content = item.get('content')
                if not content or content.get('state') != 'OPEN':
                    continue

                # 解析字段值
                fields = {}
                for fv in item.get('fieldValues', {}).get('nodes', []):
                    if not fv:
                        continue
                    field_name = fv.get('field', {}).get('name')
                    if not field_name:
                        continue

                    if 'text' in fv:
                        fields[field_name] = fv['text']
                    elif 'number' in fv:
                        fields[field_name] = fv['number']
                    elif 'date' in fv:
                        fields[field_name] = fv['date']
                    elif 'name' in fv:
                        fields[field_name] = fv['name']

                # 过滤 Done 状态
                status = fields.get('Status')
                if status and status.lower() == 'done':
                    continue

                item_data = {
                    'number': content['number'],
                    'title': content['title'],
                    'url': content['url'],
                    'state': content['state'],
                    'created_at': content.get('createdAt'),
                    'updated_at': content.get('updatedAt'),
                    'labels': [l['name'] for l in content.get('labels', {}).get('nodes', [])],
                    'assignees': [a['login'] for a in content.get('assignees', {}).get('nodes', [])],
                    'repo': content.get('repository', {}).get('name'),
                    'project': project_name,
                    'priority': fields.get('Priority'),
                    'end_date': fields.get('End date'),
                    'start_date': fields.get('Start date'),
                    'status': fields.get('Status'),
                }
                all_items.append(item_data)

            page_info = node.get('items', {}).get('pageInfo', {})
            if not page_info.get('hasNextPage'):
                break
            cursor = page_info.get('endCursor')

    print(f"\nTotal open issues: {len(all_items)}")
    return all_items


def calculate_risk(issue, today):
    """计算 Issue 风险评分"""
    score = 0
    reasons = []
    suggestions = []

    priority = issue.get('priority')
    if priority == 'P0':
        score += 40
        reasons.append("P0 最高优先级")
    elif priority == 'P1':
        score += 25
        reasons.append("P1 高优先级")
    elif priority == 'P2':
        score += 10
        reasons.append("P2 一般优先级")
    else:
        suggestions.append("建议设置优先级")

    end_date_str = issue.get('end_date')
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            days_until = (end_date - today).days
            issue['days_until_deadline'] = days_until
            issue['end_date_formatted'] = end_date.strftime('%m/%d')

            if days_until < 0:
                score += 40
                reasons.insert(0, f"已逾期 {abs(days_until)} 天")
                suggestions.append("立即处理或调整截止日期")
            elif days_until == 0:
                score += 35
                reasons.insert(0, "今天截止")
            elif days_until <= 3:
                score += 30
                reasons.insert(0, f"{days_until} 天后截止")
            elif days_until <= 7:
                score += 20
                reasons.append(f"{days_until} 天后截止")
        except:
            issue['days_until_deadline'] = None
    else:
        issue['days_until_deadline'] = None

    now = datetime.now()
    if issue.get('updated_at'):
        updated = datetime.fromisoformat(issue['updated_at'].replace('Z', '+00:00')).replace(tzinfo=None)
        days_stale = (now - updated).days
        issue['days_stale'] = days_stale
        if days_stale > 30:
            score += 15
            reasons.append(f"停滞 {days_stale} 天")
        elif days_stale > 14:
            score += 10
    else:
        issue['days_stale'] = 0

    if not issue.get('assignees'):
        score += 10
        reasons.append("无负责人")
        suggestions.append("分配负责人")

    issue['risk_score'] = min(score, 100)
    issue['risk_reasons'] = reasons
    issue['risk_suggestions'] = suggestions

    if score >= 60:
        issue['risk_level'] = 'critical'
    elif score >= 40:
        issue['risk_level'] = 'high'
    elif score >= 20:
        issue['risk_level'] = 'medium'
    else:
        issue['risk_level'] = 'low'

    issue['risk_summary'] = reasons[0] if reasons else "正常"
    return issue


def generate_html(all_issues):
    """生成 HTML Dashboard"""
    now = datetime.now()
    today = now.date()

    # 计算风险
    for issue in all_issues:
        calculate_risk(issue, today)

    # 分类统计
    p0_issues = sorted([i for i in all_issues if i.get('priority') == 'P0'],
                       key=lambda x: (x.get('days_until_deadline') or 999))
    p1_issues = sorted([i for i in all_issues if i.get('priority') == 'P1'],
                       key=lambda x: (x.get('days_until_deadline') or 999))
    p2_issues = sorted([i for i in all_issues if i.get('priority') == 'P2'],
                       key=lambda x: (x.get('days_until_deadline') or 999))
    overdue_issues = sorted([i for i in all_issues if i.get('days_until_deadline') is not None and i['days_until_deadline'] < 0],
                            key=lambda x: x['days_until_deadline'])
    due_soon = sorted([i for i in all_issues if i.get('days_until_deadline') is not None and 0 <= i['days_until_deadline'] <= 7],
                      key=lambda x: x['days_until_deadline'])

    # 标签统计
    label_stats = defaultdict(lambda: {'count': 0, 'p0': 0, 'p1': 0, 'overdue': 0, 'issues': []})
    for issue in all_issues:
        for label in issue.get('labels', []):
            label_stats[label]['count'] += 1
            label_stats[label]['issues'].append(issue)
            if issue.get('priority') == 'P0': label_stats[label]['p0'] += 1
            elif issue.get('priority') == 'P1': label_stats[label]['p1'] += 1
            if issue.get('days_until_deadline') is not None and issue['days_until_deadline'] < 0:
                label_stats[label]['overdue'] += 1

    # 负责人统计
    assignee_stats = defaultdict(lambda: {'total': 0, 'p0': 0, 'p1': 0, 'overdue': 0, 'issues': []})
    for issue in all_issues:
        for assignee in issue.get('assignees', []):
            assignee_stats[assignee]['total'] += 1
            assignee_stats[assignee]['issues'].append(issue)
            if issue.get('priority') == 'P0': assignee_stats[assignee]['p0'] += 1
            elif issue.get('priority') == 'P1': assignee_stats[assignee]['p1'] += 1
            if issue.get('days_until_deadline') is not None and issue['days_until_deadline'] < 0:
                assignee_stats[assignee]['overdue'] += 1

    unassigned = [i for i in all_issues if not i.get('assignees')]
    sorted_labels = sorted(label_stats.items(), key=lambda x: -(x[1]['overdue'] * 10 + x[1]['p0'] * 5 + x[1]['count']))
    sorted_assignees = sorted(assignee_stats.items(), key=lambda x: -(x[1]['overdue'] * 10 + x[1]['p0'] * 5 + x[1]['total']))

    # 生成 HTML (完整模板)
    html = generate_html_template(
        now=now,
        all_issues=all_issues,
        p0_issues=p0_issues,
        p1_issues=p1_issues,
        p2_issues=p2_issues,
        overdue_issues=overdue_issues,
        due_soon=due_soon,
        unassigned=unassigned,
        sorted_labels=sorted_labels,
        sorted_assignees=sorted_assignees,
        label_stats=label_stats,
        assignee_stats=assignee_stats
    )

    return html


def generate_html_template(**kwargs):
    """生成完整的 HTML 模板"""
    now = kwargs['now']
    all_issues = kwargs['all_issues']
    p0_issues = kwargs['p0_issues']
    p1_issues = kwargs['p1_issues']
    p2_issues = kwargs['p2_issues']
    overdue_issues = kwargs['overdue_issues']
    due_soon = kwargs['due_soon']
    unassigned = kwargs['unassigned']
    sorted_labels = kwargs['sorted_labels']
    sorted_assignees = kwargs['sorted_assignees']
    label_stats = kwargs['label_stats']

    html = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PM Dashboard - Issue Monitor</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        :root {
            --bg-primary: #0F172A;
            --bg-card: #1E293B;
            --bg-card-hover: #334155;
            --text-primary: #F1F5F9;
            --text-muted: #94A3B8;
            --border-color: #334155;
            --primary: #3B82F6;
            --purple: #A855F7;
            --orange: #FB923C;
            --success: #22C55E;
            --warning: #EAB308;
            --danger: #EF4444;
            --sidebar-width: 220px;
            --header-height: 130px;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        @keyframes slideIn {
            from { opacity: 0; transform: translateX(-10px); }
            to { opacity: 1; transform: translateX(0); }
        }
        .content-section { animation: fadeIn 0.4s ease-out; }
        .risk-item {
            animation: slideIn 0.3s ease-out;
            animation-fill-mode: both;
        }
        .risk-item:nth-child(1) { animation-delay: 0.05s; }
        .risk-item:nth-child(2) { animation-delay: 0.1s; }
        .risk-item:nth-child(3) { animation-delay: 0.15s; }
        .risk-item:nth-child(4) { animation-delay: 0.2s; }
        .risk-item:nth-child(5) { animation-delay: 0.25s; }
        ::-webkit-scrollbar { width: 8px; height: 8px; }
        ::-webkit-scrollbar-track { background: var(--bg-primary); }
        ::-webkit-scrollbar-thumb { background: var(--border-color); border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: var(--text-muted); }

        .sidebar {
            position: fixed;
            top: 0;
            left: 0;
            width: var(--sidebar-width);
            height: 100vh;
            background: var(--bg-card);
            border-right: 1px solid var(--border-color);
            z-index: 100;
            display: flex;
            flex-direction: column;
        }
        .sidebar-header {
            padding: 20px;
            border-bottom: 1px solid var(--border-color);
        }
        .logo-text {
            font-size: 18px;
            font-weight: 700;
            color: white;
        }
        .logo-subtitle {
            font-size: 11px;
            color: var(--text-muted);
            margin-top: 4px;
        }
        .sidebar-nav {
            flex: 1;
            padding: 16px 12px;
            overflow-y: auto;
        }
        .nav-section-title {
            font-size: 10px;
            text-transform: uppercase;
            letter-spacing: 1px;
            color: var(--text-muted);
            padding: 8px 12px;
            margin-top: 8px;
        }
        .nav-item {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 12px 16px;
            border-radius: 8px;
            color: var(--text-muted);
            cursor: pointer;
            transition: all 0.2s;
            margin-bottom: 4px;
            font-size: 13px;
        }
        .nav-item:hover {
            background: var(--bg-card-hover);
            color: var(--text-primary);
        }
        .nav-item.active {
            background: rgba(59, 130, 246, 0.15);
            color: var(--primary);
        }
        .nav-item .dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            flex-shrink: 0;
        }
        .nav-item .badge {
            margin-left: auto;
            background: var(--bg-card-hover);
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 11px;
        }
        .nav-item.active .badge {
            background: rgba(59, 130, 246, 0.3);
        }

        .top-header {
            position: fixed;
            top: 0;
            left: var(--sidebar-width);
            right: 0;
            height: var(--header-height);
            background: var(--bg-primary);
            border-bottom: 1px solid var(--border-color);
            z-index: 99;
            padding: 16px 24px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }
        .header-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .header-title {
            font-size: 18px;
            font-weight: 600;
            color: white;
        }
        .header-actions {
            display: flex;
            align-items: center;
            gap: 16px;
        }
        .search-box {
            position: relative;
            width: 240px;
        }
        .search-box input {
            width: 100%;
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 8px 12px 8px 36px;
            color: var(--text-primary);
            font-size: 13px;
            outline: none;
        }
        .search-box input:focus { border-color: var(--primary); }
        .search-box input::placeholder { color: var(--text-muted); }
        .search-icon {
            position: absolute;
            left: 12px;
            top: 50%;
            transform: translateY(-50%);
            color: var(--text-muted);
        }
        .timestamp {
            font-size: 12px;
            color: var(--text-muted);
        }

        .stats-filter-row {
            display: flex;
            align-items: center;
            gap: 16px;
        }
        .stats-row {
            display: flex;
            gap: 10px;
            flex: 1;
        }
        .stat-box {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 10px 16px;
            display: flex;
            align-items: center;
            gap: 10px;
            cursor: pointer;
            transition: all 0.2s;
            position: relative;
            overflow: hidden;
        }
        .stat-box::before {
            content: "";
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 3px;
            opacity: 0;
            transition: opacity 0.2s;
        }
        .stat-box:hover {
            border-color: var(--primary);
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        }
        .stat-box:hover::before { opacity: 1; }
        .stat-box .value { font-size: 22px; font-weight: 700; }
        .stat-box .label { font-size: 11px; color: var(--text-muted); }
        .stat-box.danger .value { color: var(--danger); }
        .stat-box.danger::before { background: var(--danger); }
        .stat-box.warning .value { color: var(--warning); }
        .stat-box.warning::before { background: var(--warning); }
        .stat-box.info .value { color: var(--primary); }
        .stat-box.info::before { background: var(--primary); }

        .customer-filter {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .filter-label {
            font-size: 12px;
            color: var(--text-muted);
        }
        .customer-select {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 10px 16px;
            color: var(--text-primary);
            font-size: 13px;
            cursor: pointer;
            min-width: 200px;
            outline: none;
        }
        .customer-select:focus { border-color: var(--primary); }
        .customer-select option {
            background: var(--bg-card);
            color: var(--text-primary);
        }

        .main-content {
            margin-left: var(--sidebar-width);
            padding: calc(var(--header-height) + 20px) 24px 24px;
        }
        .content-section {
            background: var(--bg-card);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
            border: 1px solid var(--border-color);
        }
        .section-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 16px;
            padding-bottom: 12px;
            border-bottom: 1px solid var(--border-color);
        }
        .section-title {
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 16px;
            font-weight: 600;
            color: white;
        }
        .section-title .icon {
            width: 24px;
            height: 24px;
            border-radius: 6px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 12px;
        }
        .section-title .icon.danger { background: rgba(239, 68, 68, 0.2); }
        .section-title .icon.warning { background: rgba(234, 179, 8, 0.2); }
        .section-title .icon.info { background: rgba(59, 130, 246, 0.2); }
        .section-count {
            background: var(--bg-card-hover);
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            color: var(--text-muted);
        }

        .risk-item {
            display: flex;
            align-items: flex-start;
            padding: 16px;
            background: linear-gradient(135deg, var(--bg-card) 0%, rgba(30, 41, 59, 0.8) 100%);
            border-radius: 12px;
            margin-bottom: 12px;
            border-left: 4px solid;
            transition: all 0.3s;
        }
        .risk-item:hover {
            transform: translateX(4px);
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
        }
        .risk-item.critical { border-left-color: var(--danger); background: linear-gradient(135deg, rgba(239, 68, 68, 0.1) 0%, var(--bg-card) 100%); }
        .risk-item.high { border-left-color: var(--warning); background: linear-gradient(135deg, rgba(234, 179, 8, 0.1) 0%, var(--bg-card) 100%); }
        .risk-item.medium { border-left-color: var(--primary); }
        .risk-item.low { border-left-color: var(--success); }

        .risk-priority {
            width: 40px;
            height: 40px;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 12px;
            margin-right: 16px;
            flex-shrink: 0;
        }
        .risk-priority.p0 { background: rgba(239, 68, 68, 0.2); color: var(--danger); }
        .risk-priority.p1 { background: rgba(234, 179, 8, 0.2); color: var(--warning); }
        .risk-priority.p2 { background: rgba(59, 130, 246, 0.2); color: var(--primary); }
        .risk-priority.none { background: var(--bg-card-hover); color: var(--text-muted); }
        .risk-content { flex: 1; min-width: 0; }
        .risk-title { font-size: 14px; font-weight: 500; margin-bottom: 6px; }
        .risk-title a { color: var(--text-primary); text-decoration: none; }
        .risk-title a:hover { color: var(--primary); }
        .risk-meta {
            display: flex;
            gap: 12px;
            font-size: 12px;
            color: var(--text-muted);
            flex-wrap: wrap;
            margin-bottom: 8px;
        }
        .risk-reason {
            display: inline-flex;
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 12px;
        }
        .risk-item.critical .risk-reason { background: rgba(239, 68, 68, 0.15); color: #FCA5A5; }
        .risk-item.high .risk-reason { background: rgba(234, 179, 8, 0.15); color: #FDE047; }
        .risk-item.medium .risk-reason { background: rgba(59, 130, 246, 0.15); color: #93C5FD; }
        .risk-suggestion {
            font-size: 11px;
            color: var(--text-muted);
            margin-top: 6px;
            padding-left: 12px;
            border-left: 2px solid var(--border-color);
        }

        .badge {
            display: inline-flex;
            padding: 3px 10px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 500;
        }
        .badge.danger { background: rgba(239, 68, 68, 0.2); color: #FCA5A5; }
        .badge.warning { background: rgba(234, 179, 8, 0.2); color: #FDE047; }
        .badge.info { background: rgba(59, 130, 246, 0.2); color: #93C5FD; }
        .deadline-badge {
            padding: 3px 10px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 500;
        }
        .deadline-badge.overdue { background: var(--danger); color: white; }
        .deadline-badge.urgent { background: var(--warning); color: #1E293B; }
        .deadline-badge.normal { background: var(--bg-card-hover); color: var(--text-muted); }

        .two-col {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }
        @media (max-width: 1400px) {
            .two-col { grid-template-columns: 1fr; }
        }
        .card-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 16px;
        }
        .card-item {
            background: var(--bg-card-hover);
            border-radius: 12px;
            padding: 16px;
            border: 1px solid var(--border-color);
            cursor: pointer;
            transition: all 0.2s;
        }
        .card-item:hover {
            border-color: var(--primary);
            transform: translateY(-2px);
        }
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }
        .card-name { font-size: 14px; font-weight: 600; color: white; }
        .card-count {
            background: var(--primary);
            color: white;
            padding: 2px 10px;
            border-radius: 20px;
            font-size: 12px;
        }
        .card-stats { display: flex; gap: 8px; flex-wrap: wrap; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        .empty-state {
            text-align: center;
            padding: 40px;
            color: var(--text-muted);
        }
        .empty-state-icon { font-size: 48px; margin-bottom: 16px; }
        .assignee-select {
            background: var(--bg-card-hover);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 8px 16px;
            color: var(--text-primary);
            font-size: 13px;
            min-width: 200px;
        }
        .assignee-select:focus { outline: none; border-color: var(--primary); }

        @media (max-width: 900px) {
            :root { --sidebar-width: 0px; }
            .sidebar { display: none; }
            .top-header { left: 0; }
        }
    </style>
</head>
<body>
    <aside class="sidebar">
        <div class="sidebar-header">
            <div class="logo-text">PM Dashboard</div>
            <div class="logo-subtitle">Issue Monitor</div>
        </div>
        <nav class="sidebar-nav">
            <div class="nav-section-title">导航</div>
            <div class="nav-item active" onclick="showTab('overview', this)">
                <span class="dot" style="background: var(--primary)"></span>
                总览
            </div>
            <div class="nav-item" onclick="showTab('deadline', this)">
                <span class="dot" style="background: var(--danger)"></span>
                截止日期
                <span class="badge">''' + str(len(overdue_issues) + len(due_soon)) + '''</span>
            </div>
            <div class="nav-item" onclick="showTab('priority', this)">
                <span class="dot" style="background: var(--warning)"></span>
                优先级
            </div>
            <div class="nav-item" onclick="showTab('customers', this)">
                <span class="dot" style="background: var(--purple)"></span>
                客户/标签
                <span class="badge">''' + str(len(sorted_labels)) + '''</span>
            </div>
            <div class="nav-item" onclick="showTab('assignees', this)">
                <span class="dot" style="background: var(--orange)"></span>
                负责人
            </div>
            <div class="nav-section-title">快速跳转</div>
            <div class="nav-item" onclick="showTab('deadline')">
                <span class="dot" style="background: var(--danger)"></span>
                已逾期
                <span class="badge" style="background: rgba(239, 68, 68, 0.2); color: #FCA5A5;">''' + str(len(overdue_issues)) + '''</span>
            </div>
            <div class="nav-item" onclick="showTab('priority')">
                <span class="dot" style="background: var(--danger)"></span>
                P0 紧急
                <span class="badge" style="background: rgba(239, 68, 68, 0.2); color: #FCA5A5;">''' + str(len(p0_issues)) + '''</span>
            </div>
            <div class="nav-item" onclick="showTab('assignees'); setTimeout(() => filterByAssignee('__unassigned__'), 100)">
                <span class="dot" style="background: var(--text-muted)"></span>
                未分配
                <span class="badge">''' + str(len(unassigned)) + '''</span>
            </div>
        </nav>
    </aside>

    <header class="top-header">
        <div class="header-row">
            <div class="header-title" id="currentTabTitle">总览</div>
            <div class="header-actions">
                <div class="search-box">
                    <span class="search-icon">🔍</span>
                    <input type="text" placeholder="搜索 Issue..." id="searchInput" onkeyup="searchIssues()">
                </div>
                <div class="timestamp">更新: ''' + now.strftime('%Y-%m-%d %H:%M') + '''</div>
            </div>
        </div>
        <div class="stats-filter-row">
            <div class="stats-row">
                <div class="stat-box danger" onclick="showTab('deadline')">
                    <div class="value">''' + str(len(overdue_issues)) + '''</div>
                    <div class="label">🚨 已逾期</div>
                </div>
                <div class="stat-box warning" onclick="showTab('deadline')">
                    <div class="value">''' + str(len(due_soon)) + '''</div>
                    <div class="label">⏰ 7天内</div>
                </div>
                <div class="stat-box danger" onclick="showTab('priority')">
                    <div class="value">''' + str(len(p0_issues)) + '''</div>
                    <div class="label">🔴 P0</div>
                </div>
                <div class="stat-box warning" onclick="showTab('priority')">
                    <div class="value">''' + str(len(p1_issues)) + '''</div>
                    <div class="label">🟠 P1</div>
                </div>
                <div class="stat-box info" onclick="showTab('priority')">
                    <div class="value">''' + str(len(p2_issues)) + '''</div>
                    <div class="label">🔵 P2</div>
                </div>
                <div class="stat-box" onclick="showTab('assignees'); setTimeout(() => filterByAssignee('__unassigned__'), 100)">
                    <div class="value">''' + str(len(unassigned)) + '''</div>
                    <div class="label">👤 未分配</div>
                </div>
                <div class="stat-box info">
                    <div class="value">''' + str(len(all_issues)) + '''</div>
                    <div class="label">📋 总计</div>
                </div>
            </div>
            <div class="customer-filter">
                <span class="filter-label">客户筛选:</span>
                <select class="customer-select" id="customerSelect" onchange="filterByCustomer(this.value)">
                    <option value="">全部客户 (''' + str(len(all_issues)) + ''')</option>
'''

    for label, stats in sorted_labels:
        indicator = "🔴 " if stats['overdue'] > 0 else "🟠 " if stats['p0'] > 0 else ""
        html += f'                    <option value="{label}">{indicator}{label} ({stats["count"]})</option>\n'

    html += '''
                </select>
            </div>
        </div>
    </header>

    <main class="main-content">
        <div id="tab-overview" class="tab-content active">
            <div class="two-col">
                <div class="content-section">
                    <div class="section-header">
                        <div class="section-title"><span class="icon danger">🚨</span>已逾期 Issue</div>
                        <span class="section-count">''' + str(len(overdue_issues)) + '''</span>
                    </div>
'''

    for issue in overdue_issues[:8]:
        priority = issue.get('priority') or '-'
        priority_class = priority.lower() if priority in ['P0', 'P1', 'P2'] else 'none'
        assignee_str = ', '.join(issue.get('assignees', [])) or '未分配'
        labels_str = ', '.join(issue.get('labels', [])[:2]) or '-'

        html += f'''
                    <div class="risk-item critical" data-labels="{','.join(issue.get('labels', []))}">
                        <div class="risk-priority {priority_class}">{priority}</div>
                        <div class="risk-content">
                            <div class="risk-title"><a href="{issue['url']}" target="_blank">#{issue['number']} {issue['title'][:50]}{'...' if len(issue['title']) > 50 else ''}</a></div>
                            <div class="risk-meta"><span>🏷️ {labels_str}</span><span>👤 {assignee_str}</span></div>
                            <span class="risk-reason">⚠️ 已逾期 {abs(issue['days_until_deadline'])} 天</span>
                        </div>
                    </div>
'''

    if not overdue_issues:
        html += '                    <div class="empty-state"><div class="empty-state-icon">🎉</div><p>没有逾期 Issue</p></div>'

    html += '''
                </div>
                <div class="content-section">
                    <div class="section-header">
                        <div class="section-title"><span class="icon warning">⏰</span>即将截止 (7天内)</div>
                        <span class="section-count">''' + str(len(due_soon)) + '''</span>
                    </div>
'''

    for issue in due_soon[:8]:
        priority = issue.get('priority') or '-'
        priority_class = priority.lower() if priority in ['P0', 'P1', 'P2'] else 'none'
        risk_class = 'critical' if issue['days_until_deadline'] <= 1 else 'high' if issue['days_until_deadline'] <= 3 else 'medium'
        assignee_str = ', '.join(issue.get('assignees', [])) or '未分配'
        days = issue['days_until_deadline']
        days_text = '今天截止!' if days == 0 else f'{days} 天后截止'

        html += f'''
                    <div class="risk-item {risk_class}" data-labels="{','.join(issue.get('labels', []))}">
                        <div class="risk-priority {priority_class}">{priority}</div>
                        <div class="risk-content">
                            <div class="risk-title"><a href="{issue['url']}" target="_blank">#{issue['number']} {issue['title'][:50]}{'...' if len(issue['title']) > 50 else ''}</a></div>
                            <div class="risk-meta"><span>🏷️ {', '.join(issue.get('labels', [])[:2]) or '-'}</span><span>👤 {assignee_str}</span></div>
                            <span class="risk-reason">📅 {days_text}</span>
                        </div>
                    </div>
'''

    if not due_soon:
        html += '                    <div class="empty-state"><div class="empty-state-icon">✅</div><p>暂无即将截止</p></div>'

    html += '''
                </div>
            </div>
        </div>

        <div id="tab-deadline" class="tab-content">
            <div class="two-col">
                <div class="content-section">
                    <div class="section-header">
                        <div class="section-title"><span class="icon danger">🚨</span>已逾期</div>
                        <span class="section-count">''' + str(len(overdue_issues)) + '''</span>
                    </div>
'''

    for issue in overdue_issues:
        priority = issue.get('priority') or '-'
        priority_class = priority.lower() if priority in ['P0', 'P1', 'P2'] else 'none'
        assignee_str = ', '.join(issue.get('assignees', [])) or '未分配'
        suggestion = issue['risk_suggestions'][0] if issue.get('risk_suggestions') else '请立即处理'

        html += f'''
                    <div class="risk-item critical" data-labels="{','.join(issue.get('labels', []))}">
                        <div class="risk-priority {priority_class}">{priority}</div>
                        <div class="risk-content">
                            <div class="risk-title"><a href="{issue['url']}" target="_blank">#{issue['number']} {issue['title']}</a></div>
                            <div class="risk-meta"><span>🏷️ {', '.join(issue.get('labels', [])[:2]) or '-'}</span><span>👤 {assignee_str}</span></div>
                            <span class="risk-reason">⚠️ 已逾期 {abs(issue['days_until_deadline'])} 天</span>
                            <div class="risk-suggestion">💡 {suggestion}</div>
                        </div>
                    </div>
'''

    if not overdue_issues:
        html += '                    <div class="empty-state"><div class="empty-state-icon">🎉</div><p>没有逾期</p></div>'

    html += '''
                </div>
                <div class="content-section">
                    <div class="section-header">
                        <div class="section-title"><span class="icon warning">⏰</span>7天内截止</div>
                        <span class="section-count">''' + str(len(due_soon)) + '''</span>
                    </div>
'''

    for issue in due_soon:
        priority = issue.get('priority') or '-'
        priority_class = priority.lower() if priority in ['P0', 'P1', 'P2'] else 'none'
        risk_class = 'critical' if issue['days_until_deadline'] <= 1 else 'high' if issue['days_until_deadline'] <= 3 else 'medium'
        assignee_str = ', '.join(issue.get('assignees', [])) or '未分配'
        days = issue['days_until_deadline']

        html += f'''
                    <div class="risk-item {risk_class}" data-labels="{','.join(issue.get('labels', []))}">
                        <div class="risk-priority {priority_class}">{priority}</div>
                        <div class="risk-content">
                            <div class="risk-title"><a href="{issue['url']}" target="_blank">#{issue['number']} {issue['title']}</a></div>
                            <div class="risk-meta"><span>🏷️ {', '.join(issue.get('labels', [])[:2]) or '-'}</span><span>👤 {assignee_str}</span></div>
                            <span class="risk-reason">📅 {days}天后截止</span>
                        </div>
                    </div>
'''

    if not due_soon:
        html += '                    <div class="empty-state"><div class="empty-state-icon">✅</div><p>暂无即将截止</p></div>'

    html += '''
                </div>
            </div>
        </div>

        <div id="tab-priority" class="tab-content">
            <div class="two-col">
                <div class="content-section">
                    <div class="section-header">
                        <div class="section-title"><span class="icon danger">🔴</span>P0 最高优先</div>
                        <span class="section-count">''' + str(len(p0_issues)) + '''</span>
                    </div>
'''

    for issue in p0_issues:
        assignee_str = ', '.join(issue.get('assignees', [])) or '未分配'
        deadline_html = ''
        if issue.get('end_date_formatted'):
            days = issue.get('days_until_deadline', 999)
            if days < 0:
                deadline_html = f'<span class="deadline-badge overdue">逾期{abs(days)}天</span>'
            elif days <= 7:
                deadline_html = f'<span class="deadline-badge urgent">{issue["end_date_formatted"]}</span>'

        html += f'''
                    <div class="risk-item critical" data-labels="{','.join(issue.get('labels', []))}">
                        <div class="risk-priority p0">P0</div>
                        <div class="risk-content">
                            <div class="risk-title"><a href="{issue['url']}" target="_blank">#{issue['number']} {issue['title']}</a></div>
                            <div class="risk-meta"><span>🏷️ {', '.join(issue.get('labels', [])[:2]) or '-'}</span><span>👤 {assignee_str}</span>{deadline_html}</div>
                            <span class="risk-reason">🔴 {issue['risk_summary']}</span>
                        </div>
                    </div>
'''

    if not p0_issues:
        html += '                    <div class="empty-state"><div class="empty-state-icon">✅</div><p>没有 P0</p></div>'

    html += '''
                </div>
                <div class="content-section">
                    <div class="section-header">
                        <div class="section-title"><span class="icon warning">🟠</span>P1 高优先</div>
                        <span class="section-count">''' + str(len(p1_issues)) + '''</span>
                    </div>
'''

    for issue in p1_issues[:20]:
        assignee_str = ', '.join(issue.get('assignees', [])) or '未分配'
        deadline_html = ''
        if issue.get('end_date_formatted'):
            days = issue.get('days_until_deadline', 999)
            if days < 0:
                deadline_html = f'<span class="deadline-badge overdue">逾期{abs(days)}天</span>'
            elif days <= 7:
                deadline_html = f'<span class="deadline-badge urgent">{issue["end_date_formatted"]}</span>'

        html += f'''
                    <div class="risk-item high" data-labels="{','.join(issue.get('labels', []))}">
                        <div class="risk-priority p1">P1</div>
                        <div class="risk-content">
                            <div class="risk-title"><a href="{issue['url']}" target="_blank">#{issue['number']} {issue['title'][:60]}{'...' if len(issue['title']) > 60 else ''}</a></div>
                            <div class="risk-meta"><span>🏷️ {', '.join(issue.get('labels', [])[:2]) or '-'}</span><span>👤 {assignee_str}</span>{deadline_html}</div>
                        </div>
                    </div>
'''

    html += '''
                </div>
            </div>
        </div>

        <div id="tab-customers" class="tab-content">
            <div class="content-section">
                <div class="section-header">
                    <div class="section-title"><span class="icon info">🏷️</span>按客户/标签分类</div>
                    <span class="section-count">''' + str(len(sorted_labels)) + ''' 个</span>
                </div>
                <div class="card-grid" id="customerCards">
'''

    for label, stats in sorted_labels:
        html += f'''
                    <div class="card-item" onclick="showLabelDetail('{label}')">
                        <div class="card-header">
                            <span class="card-name">{label}</span>
                            <span class="card-count">{stats['count']}</span>
                        </div>
                        <div class="card-stats">
'''
        if stats['overdue'] > 0:
            html += f'                            <span class="badge danger">{stats["overdue"]} 逾期</span>\n'
        if stats['p0'] > 0:
            html += f'                            <span class="badge danger">{stats["p0"]} P0</span>\n'
        if stats['p1'] > 0:
            html += f'                            <span class="badge warning">{stats["p1"]} P1</span>\n'
        html += '''
                        </div>
                    </div>
'''

    html += '''
                </div>
                <div id="labelIssueList" style="margin-top:20px;"></div>
            </div>
        </div>

        <div id="tab-assignees" class="tab-content">
            <div class="content-section">
                <div class="section-header">
                    <div class="section-title"><span class="icon info">👥</span>按负责人分类</div>
                    <select class="assignee-select" id="assigneeSelect" onchange="filterByAssignee(this.value)">
                        <option value="">-- 选择负责人 --</option>
                        <option value="__unassigned__">⚠️ 未分配 (''' + str(len(unassigned)) + ''')</option>
'''

    for name, stats in sorted_assignees:
        html += f'                        <option value="{name}">{name} ({stats["total"]})</option>\n'

    html += '''
                    </select>
                </div>
                <div class="card-grid" id="assigneeCards">
'''

    for name, stats in sorted_assignees[:12]:
        html += f'''
                    <div class="card-item" onclick="filterByAssignee('{name}')">
                        <div class="card-header">
                            <span class="card-name">👤 {name}</span>
                            <span class="card-count">{stats['total']}</span>
                        </div>
                        <div class="card-stats">
'''
        if stats['overdue'] > 0:
            html += f'                            <span class="badge danger">{stats["overdue"]} 逾期</span>\n'
        if stats['p0'] > 0:
            html += f'                            <span class="badge danger">{stats["p0"]} P0</span>\n'
        if stats['p1'] > 0:
            html += f'                            <span class="badge warning">{stats["p1"]} P1</span>\n'
        html += '''
                        </div>
                    </div>
'''

    html += '''
                </div>
                <div id="assigneeIssueList" style="margin-top:20px;"></div>
            </div>
        </div>
    </main>

    <script>
        const allIssues = ''' + json.dumps(all_issues, ensure_ascii=False) + ''';
        const labelData = ''' + json.dumps({k: {'count': v['count'], 'p0': v['p0'], 'p1': v['p1'], 'overdue': v['overdue'], 'issues': v['issues']} for k, v in label_stats.items()}, ensure_ascii=False) + ''';

        const tabTitles = {
            'overview': '总览',
            'deadline': '截止日期',
            'priority': '优先级',
            'customers': '客户/标签',
            'assignees': '负责人'
        };

        function showTab(tabId, navItem) {
            document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
            document.getElementById('tab-' + tabId).classList.add('active');
            document.getElementById('currentTabTitle').textContent = tabTitles[tabId] || tabId;

            if (navItem) {
                navItem.classList.add('active');
            } else {
                const navItems = document.querySelectorAll('.sidebar-nav > .nav-item');
                const tabOrder = ['overview', 'deadline', 'priority', 'customers', 'assignees'];
                const idx = tabOrder.indexOf(tabId);
                if (idx >= 0 && navItems[idx]) {
                    navItems[idx].classList.add('active');
                }
            }
        }

        function searchIssues() {
            const term = document.getElementById('searchInput').value.toLowerCase();
            document.querySelectorAll('.risk-item').forEach(item => {
                const title = item.querySelector('.risk-title')?.textContent.toLowerCase() || '';
                item.style.display = title.includes(term) ? '' : 'none';
            });
        }

        function filterByCustomer(label) {
            if (!label) {
                document.querySelectorAll('.risk-item').forEach(item => item.style.display = '');
                document.querySelectorAll('.card-item').forEach(item => item.style.display = '');
                return;
            }
            document.querySelectorAll('.risk-item').forEach(item => {
                const labels = item.dataset.labels || '';
                item.style.display = labels.split(',').includes(label) ? '' : 'none';
            });
            showTab('customers');
            showLabelDetail(label);
        }

        function showLabelDetail(label) {
            document.getElementById('customerSelect').value = label;
            const issues = labelData[label]?.issues || [];
            renderIssueList('labelIssueList', label, issues);
        }

        function filterByAssignee(assignee) {
            document.getElementById('assigneeSelect').value = assignee;
            let issues, title;
            if (assignee === '__unassigned__') {
                issues = allIssues.filter(i => !i.assignees || i.assignees.length === 0);
                title = '未分配';
            } else if (!assignee) {
                document.getElementById('assigneeIssueList').innerHTML = '';
                return;
            } else {
                issues = allIssues.filter(i => i.assignees && i.assignees.includes(assignee));
                title = assignee;
            }
            renderIssueList('assigneeIssueList', title, issues);
        }

        function renderIssueList(containerId, title, issues) {
            issues.sort((a, b) => b.risk_score - a.risk_score);
            let html = '<div class="section-header"><div class="section-title"><span class="icon info">📋</span>' + title + '</div><span class="section-count">' + issues.length + '</span></div>';
            issues.forEach(issue => {
                const priority = issue.priority || '-';
                const priorityClass = ['P0','P1','P2'].includes(priority) ? priority.toLowerCase() : 'none';
                const riskClass = issue.risk_level || 'medium';
                const assignee = issue.assignees?.length ? issue.assignees.join(', ') : '未分配';
                const labels = issue.labels?.slice(0, 2).join(', ') || '-';
                html += '<div class="risk-item ' + riskClass + '"><div class="risk-priority ' + priorityClass + '">' + priority + '</div><div class="risk-content"><div class="risk-title"><a href="' + issue.url + '" target="_blank">#' + issue.number + ' ' + issue.title + '</a></div><div class="risk-meta"><span>🏷️ ' + labels + '</span><span>👤 ' + assignee + '</span></div><span class="risk-reason">' + (issue.risk_summary || '正常') + '</span></div></div>';
            });
            document.getElementById(containerId).innerHTML = html;
        }
    </script>
</body>
</html>
'''

    return html


def main():
    """主函数"""
    if not TOKEN:
        print("Error: GITHUB_TOKEN not set")
        return

    # 获取所有 Issues
    all_issues = fetch_all_issues()

    # 生成 HTML
    html = generate_html(all_issues)

    # 保存到 public 目录
    output_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'public')
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, 'index.html')

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"Dashboard generated: {output_path}")
    print(f"Total issues: {len(all_issues)}")


if __name__ == '__main__':
    main()
