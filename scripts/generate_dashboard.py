#!/usr/bin/env python3
"""
PM Dashboard Generator
自动从 GitHub Projects 获取 Issue 数据并生成 HTML 报告
支持与昨天数据对比，显示变化
"""

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# 东京时区 (UTC+9)
JST = timezone(timedelta(hours=9))

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

# 获取项目根目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(PROJECT_DIR, 'data')
PUBLIC_DIR = os.path.join(PROJECT_DIR, 'public')


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


def save_snapshot(issues, date_str):
    """保存当天数据快照"""
    os.makedirs(DATA_DIR, exist_ok=True)
    filepath = os.path.join(DATA_DIR, f'{date_str}.json')
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(issues, f, ensure_ascii=False, indent=2)
    print(f"Snapshot saved: {filepath}")


def load_snapshot(date_str):
    """加载指定日期的数据快照"""
    filepath = os.path.join(DATA_DIR, f'{date_str}.json')
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def compare_data(today_issues, yesterday_issues):
    """对比今天和昨天的数据，计算变化"""
    changes = {
        'new_issues': [],           # 新增 issue
        'closed_issues': [],        # 已关闭 issue
        'new_overdue': [],          # 新逾期
        'priority_up': [],          # 优先级提升
        'priority_down': [],        # 优先级降低
        'new_assigned': [],         # 新分配负责人
        'deadline_changed': [],     # 截止日期变更
    }

    if not yesterday_issues:
        # 没有昨天数据，所有都标记为新增
        changes['new_issues'] = [i['number'] for i in today_issues]
        return changes

    # 构建昨天数据的索引
    yesterday_map = {i['number']: i for i in yesterday_issues}
    today_map = {i['number']: i for i in today_issues}

    # 检查新增和变化
    for issue in today_issues:
        num = issue['number']
        if num not in yesterday_map:
            changes['new_issues'].append(num)
        else:
            old = yesterday_map[num]
            # 检查优先级变化
            old_p = old.get('priority')
            new_p = issue.get('priority')
            priority_order = {'P0': 0, 'P1': 1, 'P2': 2, None: 3}
            if old_p != new_p:
                if priority_order.get(new_p, 3) < priority_order.get(old_p, 3):
                    changes['priority_up'].append({'number': num, 'old': old_p, 'new': new_p})
                elif priority_order.get(new_p, 3) > priority_order.get(old_p, 3):
                    changes['priority_down'].append({'number': num, 'old': old_p, 'new': new_p})

            # 检查截止日期变化
            if old.get('end_date') != issue.get('end_date'):
                changes['deadline_changed'].append({
                    'number': num,
                    'old': old.get('end_date'),
                    'new': issue.get('end_date')
                })

            # 检查负责人变化（新分配）
            old_assignees = set(old.get('assignees', []))
            new_assignees = set(issue.get('assignees', []))
            if not old_assignees and new_assignees:
                changes['new_assigned'].append(num)

    # 检查已关闭（昨天有，今天没有）
    for num in yesterday_map:
        if num not in today_map:
            changes['closed_issues'].append(num)

    return changes


def calculate_risk(issue, today, changes):
    """计算 Issue 风险评分，并标记变化"""
    score = 0
    reasons = []
    suggestions = []
    issue_changes = []

    num = issue['number']

    # 标记变化
    if num in changes.get('new_issues', []):
        issue_changes.append('new')
    for p in changes.get('priority_up', []):
        if p['number'] == num:
            issue_changes.append(f"priority_up:{p['old']}→{p['new']}")
    for p in changes.get('priority_down', []):
        if p['number'] == num:
            issue_changes.append(f"priority_down:{p['old']}→{p['new']}")
    if num in changes.get('new_assigned', []):
        issue_changes.append('new_assigned')
    for d in changes.get('deadline_changed', []):
        if d['number'] == num:
            issue_changes.append('deadline_changed')

    issue['changes'] = issue_changes

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
                # 检查是否是新逾期
                if 'new' not in issue_changes:
                    # 可以进一步检查昨天是否已经逾期
                    pass
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

    now = datetime.now(JST)
    if issue.get('updated_at'):
        updated = datetime.fromisoformat(issue['updated_at'].replace('Z', '+00:00'))
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


def get_trend_html(current, previous, reverse=False):
    """生成趋势 HTML（箭头和数字变化）"""
    if previous is None:
        return ''
    diff = current - previous
    if diff == 0:
        return '<span class="trend neutral">-</span>'
    elif diff > 0:
        color = 'down' if reverse else 'up'
        return f'<span class="trend {color}">+{diff}↑</span>'
    else:
        color = 'up' if reverse else 'down'
        return f'<span class="trend {color}">{diff}↓</span>'


def get_change_badge(issue):
    """生成 issue 的变化标签 HTML"""
    changes = issue.get('changes', [])
    if not changes:
        return ''

    badges = []
    for change in changes:
        if change == 'new':
            badges.append('<span class="change-badge new">🆕 新增</span>')
        elif change.startswith('priority_up:'):
            detail = change.split(':')[1]
            badges.append(f'<span class="change-badge priority-up">⬆️ {detail}</span>')
        elif change.startswith('priority_down:'):
            detail = change.split(':')[1]
            badges.append(f'<span class="change-badge priority-down">⬇️ {detail}</span>')
        elif change == 'new_assigned':
            badges.append('<span class="change-badge assigned">👤 新分配</span>')
        elif change == 'deadline_changed':
            badges.append('<span class="change-badge deadline">📅 截止日变更</span>')

    return ' '.join(badges)


def generate_html(all_issues, changes, yesterday_stats):
    """生成 HTML Dashboard"""
    now = datetime.now(JST)
    today = now.date()

    # 计算风险
    for issue in all_issues:
        calculate_risk(issue, today, changes)

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

    # 当前统计
    current_stats = {
        'total': len(all_issues),
        'overdue': len(overdue_issues),
        'due_soon': len(due_soon),
        'p0': len(p0_issues),
        'p1': len(p1_issues),
        'p2': len(p2_issues),
        'unassigned': len(unassigned),
    }

    # 生成趋势 HTML
    trends = {}
    if yesterday_stats:
        trends['overdue'] = get_trend_html(current_stats['overdue'], yesterday_stats.get('overdue'))
        trends['due_soon'] = get_trend_html(current_stats['due_soon'], yesterday_stats.get('due_soon'))
        trends['p0'] = get_trend_html(current_stats['p0'], yesterday_stats.get('p0'))
        trends['p1'] = get_trend_html(current_stats['p1'], yesterday_stats.get('p1'))
        trends['p2'] = get_trend_html(current_stats['p2'], yesterday_stats.get('p2'))
        trends['unassigned'] = get_trend_html(current_stats['unassigned'], yesterday_stats.get('unassigned'))
        trends['total'] = get_trend_html(current_stats['total'], yesterday_stats.get('total'))
    else:
        for k in ['overdue', 'due_soon', 'p0', 'p1', 'p2', 'unassigned', 'total']:
            trends[k] = ''

    # 变化摘要
    has_changes = bool(changes.get('new_issues') or changes.get('closed_issues') or
                       changes.get('priority_up') or changes.get('priority_down'))

    # 生成 HTML
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
        current_stats=current_stats,
        trends=trends,
        changes=changes,
        has_changes=has_changes,
    )

    return html, current_stats


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
    current_stats = kwargs['current_stats']
    trends = kwargs['trends']
    changes = kwargs['changes']
    has_changes = kwargs['has_changes']

    # 变化摘要 HTML
    changes_summary_html = ''
    if has_changes:
        new_count = len(changes.get('new_issues', []))
        closed_count = len(changes.get('closed_issues', []))
        priority_up_count = len(changes.get('priority_up', []))
        priority_down_count = len(changes.get('priority_down', []))
        deadline_count = len(changes.get('deadline_changed', []))
        assigned_count = len(changes.get('new_assigned', []))

        changes_summary_html = f'''
            <div class="changes-summary">
                <div class="changes-header">
                    <span class="changes-icon">📈</span>
                    <span class="changes-title">今日变化</span>
                    <span class="changes-subtitle">vs 昨天</span>
                </div>
                <div class="changes-items">
                    {'<div class="change-item new"><span class="change-value">+' + str(new_count) + '</span><span class="change-label">🆕 新增</span></div>' if new_count else ''}
                    {'<div class="change-item closed"><span class="change-value">-' + str(closed_count) + '</span><span class="change-label">✅ 已关闭</span></div>' if closed_count else ''}
                    {'<div class="change-item up"><span class="change-value">' + str(priority_up_count) + '</span><span class="change-label">⬆️ 优先级提升</span></div>' if priority_up_count else ''}
                    {'<div class="change-item down"><span class="change-value">' + str(priority_down_count) + '</span><span class="change-label">⬇️ 优先级降低</span></div>' if priority_down_count else ''}
                    {'<div class="change-item deadline"><span class="change-value">' + str(deadline_count) + '</span><span class="change-label">📅 截止日变更</span></div>' if deadline_count else ''}
                    {'<div class="change-item assigned"><span class="change-value">' + str(assigned_count) + '</span><span class="change-label">👤 新分配</span></div>' if assigned_count else ''}
                </div>
            </div>
        '''

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
            --header-height: 180px;
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
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.6; }
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

        /* 变化摘要 */
        .changes-summary {
            background: linear-gradient(135deg, rgba(59, 130, 246, 0.15) 0%, rgba(168, 85, 247, 0.15) 100%);
            border: 1px solid rgba(59, 130, 246, 0.3);
            border-radius: 12px;
            padding: 12px 16px;
            margin-bottom: 12px;
        }
        .changes-header {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 10px;
        }
        .changes-icon { font-size: 16px; }
        .changes-title { font-weight: 600; font-size: 14px; color: white; }
        .changes-subtitle { font-size: 11px; color: var(--text-muted); }
        .changes-items {
            display: flex;
            gap: 16px;
            flex-wrap: wrap;
        }
        .change-item {
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 12px;
        }
        .change-item.new { background: rgba(34, 197, 94, 0.2); color: #86EFAC; }
        .change-item.closed { background: rgba(59, 130, 246, 0.2); color: #93C5FD; }
        .change-item.up { background: rgba(239, 68, 68, 0.2); color: #FCA5A5; }
        .change-item.down { background: rgba(234, 179, 8, 0.2); color: #FDE047; }
        .change-item.deadline { background: rgba(168, 85, 247, 0.2); color: #D8B4FE; }
        .change-item.assigned { background: rgba(251, 146, 60, 0.2); color: #FDBA74; }
        .change-value { font-weight: 700; }

        /* 趋势指示器 */
        .trend {
            font-size: 11px;
            margin-left: 4px;
            padding: 1px 4px;
            border-radius: 4px;
        }
        .trend.up { color: #FCA5A5; background: rgba(239, 68, 68, 0.2); }
        .trend.down { color: #86EFAC; background: rgba(34, 197, 94, 0.2); }
        .trend.neutral { color: var(--text-muted); }

        /* 变化标签 */
        .change-badge {
            display: inline-flex;
            align-items: center;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 500;
            margin-left: 8px;
            animation: pulse 2s infinite;
        }
        .change-badge.new { background: rgba(34, 197, 94, 0.3); color: #86EFAC; }
        .change-badge.priority-up { background: rgba(239, 68, 68, 0.3); color: #FCA5A5; }
        .change-badge.priority-down { background: rgba(234, 179, 8, 0.3); color: #FDE047; }
        .change-badge.assigned { background: rgba(251, 146, 60, 0.3); color: #FDBA74; }
        .change-badge.deadline { background: rgba(168, 85, 247, 0.3); color: #D8B4FE; }

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
        .logo-text { font-size: 18px; font-weight: 700; color: white; }
        .logo-subtitle { font-size: 11px; color: var(--text-muted); margin-top: 4px; }
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
        .nav-item:hover { background: var(--bg-card-hover); color: var(--text-primary); }
        .nav-item.active { background: rgba(59, 130, 246, 0.15); color: var(--primary); }
        .nav-item .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
        .nav-item .badge {
            margin-left: auto;
            background: var(--bg-card-hover);
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 11px;
        }
        .nav-item.active .badge { background: rgba(59, 130, 246, 0.3); }

        .top-header {
            position: fixed;
            top: 0;
            left: var(--sidebar-width);
            right: 0;
            height: var(--header-height);
            background: var(--bg-primary);
            border-bottom: 1px solid var(--border-color);
            z-index: 99;
            padding: 12px 24px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }
        .header-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .header-title { font-size: 18px; font-weight: 600; color: white; }
        .header-actions { display: flex; align-items: center; gap: 16px; }
        .search-box { position: relative; width: 240px; }
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
        .timestamp { font-size: 12px; color: var(--text-muted); }

        .stats-filter-row {
            display: flex;
            align-items: center;
            gap: 16px;
        }
        .stats-row { display: flex; gap: 8px; flex: 1; flex-wrap: wrap; }
        .stat-box {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 8px 14px;
            display: flex;
            align-items: center;
            gap: 8px;
            cursor: pointer;
            transition: all 0.2s;
            position: relative;
            overflow: hidden;
        }
        .stat-box::before {
            content: "";
            position: absolute;
            top: 0; left: 0; right: 0;
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
        .stat-box .value { font-size: 20px; font-weight: 700; }
        .stat-box .label { font-size: 10px; color: var(--text-muted); }
        .stat-box.danger .value { color: var(--danger); }
        .stat-box.danger::before { background: var(--danger); }
        .stat-box.warning .value { color: var(--warning); }
        .stat-box.warning::before { background: var(--warning); }
        .stat-box.info .value { color: var(--primary); }
        .stat-box.info::before { background: var(--primary); }

        .customer-filter { display: flex; align-items: center; gap: 10px; }
        .filter-label { font-size: 12px; color: var(--text-muted); }
        .customer-select {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 8px 14px;
            color: var(--text-primary);
            font-size: 13px;
            cursor: pointer;
            min-width: 180px;
            outline: none;
        }
        .customer-select:focus { border-color: var(--primary); }
        .customer-select option { background: var(--bg-card); color: var(--text-primary); }

        .main-content {
            margin-left: var(--sidebar-width);
            padding: calc(var(--header-height) + 16px) 24px 24px;
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
            width: 24px; height: 24px;
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
            padding: 14px;
            background: linear-gradient(135deg, var(--bg-card) 0%, rgba(30, 41, 59, 0.8) 100%);
            border-radius: 12px;
            margin-bottom: 10px;
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
        .risk-item.has-change { box-shadow: 0 0 0 1px rgba(34, 197, 94, 0.5); }

        .risk-priority {
            width: 36px; height: 36px;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 11px;
            margin-right: 14px;
            flex-shrink: 0;
        }
        .risk-priority.p0 { background: rgba(239, 68, 68, 0.2); color: var(--danger); }
        .risk-priority.p1 { background: rgba(234, 179, 8, 0.2); color: var(--warning); }
        .risk-priority.p2 { background: rgba(59, 130, 246, 0.2); color: var(--primary); }
        .risk-priority.none { background: var(--bg-card-hover); color: var(--text-muted); }
        .risk-content { flex: 1; min-width: 0; }
        .risk-title { font-size: 13px; font-weight: 500; margin-bottom: 4px; display: flex; align-items: center; flex-wrap: wrap; }
        .risk-title a { color: var(--text-primary); text-decoration: none; }
        .risk-title a:hover { color: var(--primary); }
        .risk-meta {
            display: flex;
            gap: 10px;
            font-size: 11px;
            color: var(--text-muted);
            flex-wrap: wrap;
            margin-bottom: 6px;
        }
        .risk-reason {
            display: inline-flex;
            padding: 3px 8px;
            border-radius: 6px;
            font-size: 11px;
        }
        .risk-item.critical .risk-reason { background: rgba(239, 68, 68, 0.15); color: #FCA5A5; }
        .risk-item.high .risk-reason { background: rgba(234, 179, 8, 0.15); color: #FDE047; }
        .risk-item.medium .risk-reason { background: rgba(59, 130, 246, 0.15); color: #93C5FD; }
        .risk-suggestion {
            font-size: 10px;
            color: var(--text-muted);
            margin-top: 4px;
            padding-left: 10px;
            border-left: 2px solid var(--border-color);
        }

        .badge {
            display: inline-flex;
            padding: 2px 8px;
            border-radius: 20px;
            font-size: 10px;
            font-weight: 500;
        }
        .badge.danger { background: rgba(239, 68, 68, 0.2); color: #FCA5A5; }
        .badge.warning { background: rgba(234, 179, 8, 0.2); color: #FDE047; }
        .badge.info { background: rgba(59, 130, 246, 0.2); color: #93C5FD; }
        .deadline-badge {
            padding: 2px 8px;
            border-radius: 20px;
            font-size: 10px;
            font-weight: 500;
        }
        .deadline-badge.overdue { background: var(--danger); color: white; }
        .deadline-badge.urgent { background: var(--warning); color: #1E293B; }
        .deadline-badge.normal { background: var(--bg-card-hover); color: var(--text-muted); }

        .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .three-col { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; }
        @media (max-width: 1600px) { .three-col { grid-template-columns: 1fr 1fr; } }
        @media (max-width: 1400px) { .two-col { grid-template-columns: 1fr; } }
        @media (max-width: 1200px) { .three-col { grid-template-columns: 1fr; } }

        .card-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
            gap: 14px;
        }
        .card-item {
            background: var(--bg-card-hover);
            border-radius: 12px;
            padding: 14px;
            border: 1px solid var(--border-color);
            cursor: pointer;
            transition: all 0.2s;
        }
        .card-item:hover { border-color: var(--primary); transform: translateY(-2px); }
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }
        .card-name { font-size: 13px; font-weight: 600; color: white; }
        .card-count {
            background: var(--primary);
            color: white;
            padding: 2px 8px;
            border-radius: 20px;
            font-size: 11px;
        }
        .card-stats { display: flex; gap: 6px; flex-wrap: wrap; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        .empty-state { text-align: center; padding: 40px; color: var(--text-muted); }
        .empty-state-icon { font-size: 48px; margin-bottom: 16px; }
        .assignee-select {
            background: var(--bg-card-hover);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 8px 14px;
            color: var(--text-primary);
            font-size: 12px;
            min-width: 180px;
        }
        .assignee-select:focus { outline: none; border-color: var(--primary); }

        @media (max-width: 900px) {
            :root { --sidebar-width: 0px; --header-height: 220px; }
            .sidebar { display: none; }
            .top-header { left: 0; }
            .stats-row { gap: 6px; }
            .stat-box { padding: 6px 10px; }
            .stat-box .value { font-size: 16px; }
        }

        /* 刷新按钮 */
        .refresh-btn {
            display: flex;
            align-items: center;
            gap: 6px;
            background: linear-gradient(135deg, var(--primary) 0%, var(--purple) 100%);
            border: none;
            border-radius: 8px;
            padding: 8px 14px;
            color: white;
            font-size: 12px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.3s;
        }
        .refresh-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(59, 130, 246, 0.4);
        }
        .refresh-btn:disabled {
            opacity: 0.7;
            cursor: not-allowed;
            transform: none;
        }
        .refresh-btn.loading .refresh-icon {
            animation: spin 1s linear infinite;
        }
        @keyframes spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }
        .refresh-btn .refresh-icon {
            display: inline-block;
        }

        /* 更新状态弹窗 */
        .refresh-modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.7);
            z-index: 1000;
            justify-content: center;
            align-items: center;
        }
        .refresh-modal.active { display: flex; }
        .refresh-modal-content {
            background: var(--bg-card);
            border-radius: 16px;
            padding: 32px 48px;
            text-align: center;
            border: 1px solid var(--border-color);
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.5);
        }
        .refresh-modal-icon {
            font-size: 48px;
            margin-bottom: 16px;
            animation: spin 2s linear infinite;
            display: inline-block;
        }
        .refresh-modal-title {
            font-size: 18px;
            font-weight: 600;
            color: white;
            margin-bottom: 8px;
        }
        .refresh-modal-text {
            font-size: 13px;
            color: var(--text-muted);
            margin-bottom: 16px;
        }
        .refresh-modal-progress {
            width: 200px;
            height: 4px;
            background: var(--bg-card-hover);
            border-radius: 2px;
            overflow: hidden;
            margin: 0 auto;
        }
        .refresh-modal-progress-bar {
            height: 100%;
            background: linear-gradient(90deg, var(--primary), var(--purple));
            width: 0%;
            transition: width 0.5s ease-out;
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
                <button class="refresh-btn" id="refreshBtn" onclick="triggerRefresh()" title="手动更新数据">
                    <span class="refresh-icon">🔄</span>
                    <span class="refresh-text">更新</span>
                </button>
            </div>
        </div>
        ''' + changes_summary_html + '''
        <div class="stats-filter-row">
            <div class="stats-row">
                <div class="stat-box danger" onclick="showTab('deadline')">
                    <div class="value">''' + str(current_stats['overdue']) + '''</div>
                    <div class="label">🚨 已逾期 ''' + trends['overdue'] + '''</div>
                </div>
                <div class="stat-box warning" onclick="showTab('deadline')">
                    <div class="value">''' + str(current_stats['due_soon']) + '''</div>
                    <div class="label">⏰ 7天内 ''' + trends['due_soon'] + '''</div>
                </div>
                <div class="stat-box danger" onclick="showTab('priority')">
                    <div class="value">''' + str(current_stats['p0']) + '''</div>
                    <div class="label">🔴 P0 ''' + trends['p0'] + '''</div>
                </div>
                <div class="stat-box warning" onclick="showTab('priority')">
                    <div class="value">''' + str(current_stats['p1']) + '''</div>
                    <div class="label">🟠 P1 ''' + trends['p1'] + '''</div>
                </div>
                <div class="stat-box info" onclick="showTab('priority')">
                    <div class="value">''' + str(current_stats['p2']) + '''</div>
                    <div class="label">🔵 P2 ''' + trends['p2'] + '''</div>
                </div>
                <div class="stat-box" onclick="showTab('assignees'); setTimeout(() => filterByAssignee('__unassigned__'), 100)">
                    <div class="value">''' + str(current_stats['unassigned']) + '''</div>
                    <div class="label">👤 未分配 ''' + trends['unassigned'] + '''</div>
                </div>
                <div class="stat-box info">
                    <div class="value">''' + str(current_stats['total']) + '''</div>
                    <div class="label">📋 总计 ''' + trends['total'] + '''</div>
                </div>
            </div>
            <div class="customer-filter">
                <span class="filter-label">客户:</span>
                <select class="customer-select" id="customerSelect" onchange="filterByCustomer(this.value)">
                    <option value="">全部 (''' + str(len(all_issues)) + ''')</option>
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
        change_badge = get_change_badge(issue)
        has_change_class = 'has-change' if issue.get('changes') else ''

        html += f'''
                    <div class="risk-item critical {has_change_class}" data-labels="{','.join(issue.get('labels', []))}">
                        <div class="risk-priority {priority_class}">{priority}</div>
                        <div class="risk-content">
                            <div class="risk-title"><a href="{issue['url']}" target="_blank">#{issue['number']} {issue['title'][:45]}{'...' if len(issue['title']) > 45 else ''}</a>{change_badge}</div>
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
        change_badge = get_change_badge(issue)
        has_change_class = 'has-change' if issue.get('changes') else ''

        html += f'''
                    <div class="risk-item {risk_class} {has_change_class}" data-labels="{','.join(issue.get('labels', []))}">
                        <div class="risk-priority {priority_class}">{priority}</div>
                        <div class="risk-content">
                            <div class="risk-title"><a href="{issue['url']}" target="_blank">#{issue['number']} {issue['title'][:45]}{'...' if len(issue['title']) > 45 else ''}</a>{change_badge}</div>
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
        change_badge = get_change_badge(issue)
        has_change_class = 'has-change' if issue.get('changes') else ''

        html += f'''
                    <div class="risk-item critical {has_change_class}" data-labels="{','.join(issue.get('labels', []))}">
                        <div class="risk-priority {priority_class}">{priority}</div>
                        <div class="risk-content">
                            <div class="risk-title"><a href="{issue['url']}" target="_blank">#{issue['number']} {issue['title']}</a>{change_badge}</div>
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
        change_badge = get_change_badge(issue)
        has_change_class = 'has-change' if issue.get('changes') else ''

        html += f'''
                    <div class="risk-item {risk_class} {has_change_class}" data-labels="{','.join(issue.get('labels', []))}">
                        <div class="risk-priority {priority_class}">{priority}</div>
                        <div class="risk-content">
                            <div class="risk-title"><a href="{issue['url']}" target="_blank">#{issue['number']} {issue['title']}</a>{change_badge}</div>
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
            <div class="three-col">
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
        change_badge = get_change_badge(issue)
        has_change_class = 'has-change' if issue.get('changes') else ''

        html += f'''
                    <div class="risk-item critical {has_change_class}" data-labels="{','.join(issue.get('labels', []))}">
                        <div class="risk-priority p0">P0</div>
                        <div class="risk-content">
                            <div class="risk-title"><a href="{issue['url']}" target="_blank">#{issue['number']} {issue['title'][:50]}{'...' if len(issue['title']) > 50 else ''}</a>{change_badge}</div>
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
        change_badge = get_change_badge(issue)
        has_change_class = 'has-change' if issue.get('changes') else ''

        html += f'''
                    <div class="risk-item high {has_change_class}" data-labels="{','.join(issue.get('labels', []))}">
                        <div class="risk-priority p1">P1</div>
                        <div class="risk-content">
                            <div class="risk-title"><a href="{issue['url']}" target="_blank">#{issue['number']} {issue['title'][:50]}{'...' if len(issue['title']) > 50 else ''}</a>{change_badge}</div>
                            <div class="risk-meta"><span>🏷️ {', '.join(issue.get('labels', [])[:2]) or '-'}</span><span>👤 {assignee_str}</span>{deadline_html}</div>
                        </div>
                    </div>
'''

    html += '''
                </div>
                <div class="content-section">
                    <div class="section-header">
                        <div class="section-title"><span class="icon info">🔵</span>P2 一般优先</div>
                        <span class="section-count">''' + str(len(p2_issues)) + '''</span>
                    </div>
'''

    for issue in p2_issues[:20]:
        assignee_str = ', '.join(issue.get('assignees', [])) or '未分配'
        deadline_html = ''
        if issue.get('end_date_formatted'):
            days = issue.get('days_until_deadline', 999)
            if days < 0:
                deadline_html = f'<span class="deadline-badge overdue">逾期{abs(days)}天</span>'
            elif days <= 7:
                deadline_html = f'<span class="deadline-badge urgent">{issue["end_date_formatted"]}</span>'
        change_badge = get_change_badge(issue)
        has_change_class = 'has-change' if issue.get('changes') else ''

        html += f'''
                    <div class="risk-item medium {has_change_class}" data-labels="{','.join(issue.get('labels', []))}">
                        <div class="risk-priority p2">P2</div>
                        <div class="risk-content">
                            <div class="risk-title"><a href="{issue['url']}" target="_blank">#{issue['number']} {issue['title'][:50]}{'...' if len(issue['title']) > 50 else ''}</a>{change_badge}</div>
                            <div class="risk-meta"><span>🏷️ {', '.join(issue.get('labels', [])[:2]) or '-'}</span><span>👤 {assignee_str}</span>{deadline_html}</div>
                        </div>
                    </div>
'''

    if not p2_issues:
        html += '                    <div class="empty-state"><div class="empty-state-icon">✅</div><p>没有 P2</p></div>'

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
                <div class="section-header" id="assigneeHeader">
                    <div class="section-title" id="assigneeTitle"><span class="icon info">👥</span>按负责人分类</div>
                    <select class="assignee-select" id="assigneeSelect" onchange="filterByAssignee(this.value)">
                        <option value="">-- 全部负责人 --</option>
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
            const cardsSection = document.getElementById('assigneeCards');
            const titleSection = document.getElementById('assigneeTitle');

            let issues, title;
            if (assignee === '__unassigned__') {
                issues = allIssues.filter(i => !i.assignees || i.assignees.length === 0);
                title = '未分配';
                if (cardsSection) cardsSection.style.display = 'none';
                if (titleSection) titleSection.style.display = 'none';
            } else if (!assignee) {
                document.getElementById('assigneeIssueList').innerHTML = '';
                if (cardsSection) cardsSection.style.display = '';
                if (titleSection) titleSection.style.display = '';
                return;
            } else {
                issues = allIssues.filter(i => i.assignees && i.assignees.includes(assignee));
                title = assignee;
                if (cardsSection) cardsSection.style.display = '';
                if (titleSection) titleSection.style.display = '';
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
                const changes = issue.changes || [];
                let changeBadges = '';
                changes.forEach(c => {
                    if (c === 'new') changeBadges += '<span class="change-badge new">🆕 新增</span>';
                    else if (c.startsWith('priority_up:')) changeBadges += '<span class="change-badge priority-up">⬆️ ' + c.split(':')[1] + '</span>';
                    else if (c.startsWith('priority_down:')) changeBadges += '<span class="change-badge priority-down">⬇️ ' + c.split(':')[1] + '</span>';
                    else if (c === 'new_assigned') changeBadges += '<span class="change-badge assigned">👤 新分配</span>';
                    else if (c === 'deadline_changed') changeBadges += '<span class="change-badge deadline">📅 截止日变更</span>';
                });
                const hasChange = changes.length > 0 ? 'has-change' : '';
                html += '<div class="risk-item ' + riskClass + ' ' + hasChange + '"><div class="risk-priority ' + priorityClass + '">' + priority + '</div><div class="risk-content"><div class="risk-title"><a href="' + issue.url + '" target="_blank">#' + issue.number + ' ' + issue.title + '</a>' + changeBadges + '</div><div class="risk-meta"><span>🏷️ ' + labels + '</span><span>👤 ' + assignee + '</span></div><span class="risk-reason">' + (issue.risk_summary || '正常') + '</span></div></div>';
            });
            document.getElementById(containerId).innerHTML = html;
        }

        // 手动刷新功能
        async function triggerRefresh() {
            const btn = document.getElementById('refreshBtn');
            const modal = document.getElementById('refreshModal');
            const progressBar = document.getElementById('progressBar');
            const statusText = document.getElementById('refreshStatus');

            // 禁用按钮，显示加载状态
            btn.disabled = true;
            btn.classList.add('loading');
            btn.querySelector('.refresh-text').textContent = '触发中...';

            try {
                // 调用 Netlify Function 触发 GitHub Actions
                const response = await fetch('/.netlify/functions/trigger-update', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });

                const result = await response.json();

                if (response.ok && result.success) {
                    // 显示进度弹窗
                    modal.classList.add('active');
                    btn.querySelector('.refresh-text').textContent = '更新中...';

                    // 模拟进度条 (90秒)
                    const totalTime = 90000;
                    const interval = 500;
                    let elapsed = 0;

                    const progressInterval = setInterval(() => {
                        elapsed += interval;
                        const progress = Math.min((elapsed / totalTime) * 100, 95);
                        progressBar.style.width = progress + '%';

                        if (elapsed < 10000) {
                            statusText.textContent = '正在触发 GitHub Actions...';
                        } else if (elapsed < 30000) {
                            statusText.textContent = '正在获取最新 Issue 数据...';
                        } else if (elapsed < 60000) {
                            statusText.textContent = '正在生成 Dashboard...';
                        } else if (elapsed < 80000) {
                            statusText.textContent = '正在部署到 Netlify...';
                        } else {
                            statusText.textContent = '即将完成，准备刷新页面...';
                        }

                        if (elapsed >= totalTime) {
                            clearInterval(progressInterval);
                            progressBar.style.width = '100%';
                            statusText.textContent = '更新完成！正在刷新...';
                            setTimeout(() => {
                                window.location.reload();
                            }, 1000);
                        }
                    }, interval);

                } else {
                    // 显示详细错误
                    const errorMsg = result.error || 'Failed to trigger update';
                    const details = result.details || '';
                    throw new Error(errorMsg + (details ? '\\n\\n详情: ' + details : ''));
                }

            } catch (error) {
                console.error('Refresh error:', error);
                alert('触发更新失败: ' + error.message);
                btn.disabled = false;
                btn.classList.remove('loading');
                btn.querySelector('.refresh-text').textContent = '更新';
            }
        }
    </script>

    <!-- 刷新进度弹窗 -->
    <div class="refresh-modal" id="refreshModal">
        <div class="refresh-modal-content">
            <div class="refresh-modal-icon">🔄</div>
            <div class="refresh-modal-title">正在更新数据</div>
            <div class="refresh-modal-text" id="refreshStatus">正在触发 GitHub Actions...</div>
            <div class="refresh-modal-progress">
                <div class="refresh-modal-progress-bar" id="progressBar"></div>
            </div>
        </div>
    </div>
</body>
</html>
'''

    return html


def main():
    """主函数"""
    if not TOKEN:
        print("Error: GITHUB_TOKEN not set")
        return

    # 使用东京时区
    now = datetime.now(JST)
    today_str = now.strftime('%Y-%m-%d')
    yesterday_str = (now - timedelta(days=1)).strftime('%Y-%m-%d')
    print(f"Tokyo time: {now.strftime('%Y-%m-%d %H:%M:%S')} JST")

    # 获取所有 Issues
    all_issues = fetch_all_issues()

    # 加载昨天的数据
    yesterday_issues = load_snapshot(yesterday_str)
    if yesterday_issues:
        print(f"Loaded yesterday's data: {len(yesterday_issues)} issues")
    else:
        print("No yesterday's data found (first run or data missing)")

    # 计算昨天的统计数据
    yesterday_stats = None
    if yesterday_issues:
        yesterday_today = (now - timedelta(days=1)).date()
        y_overdue = len([i for i in yesterday_issues if i.get('end_date') and
                         datetime.strptime(i['end_date'], '%Y-%m-%d').date() < yesterday_today])
        y_due_soon = len([i for i in yesterday_issues if i.get('end_date') and
                          0 <= (datetime.strptime(i['end_date'], '%Y-%m-%d').date() - yesterday_today).days <= 7])
        yesterday_stats = {
            'total': len(yesterday_issues),
            'overdue': y_overdue,
            'due_soon': y_due_soon,
            'p0': len([i for i in yesterday_issues if i.get('priority') == 'P0']),
            'p1': len([i for i in yesterday_issues if i.get('priority') == 'P1']),
            'p2': len([i for i in yesterday_issues if i.get('priority') == 'P2']),
            'unassigned': len([i for i in yesterday_issues if not i.get('assignees')]),
        }

    # 对比数据
    changes = compare_data(all_issues, yesterday_issues)
    print(f"Changes: +{len(changes['new_issues'])} new, -{len(changes['closed_issues'])} closed, "
          f"{len(changes['priority_up'])} priority up, {len(changes['priority_down'])} priority down")

    # 生成 HTML
    html, current_stats = generate_html(all_issues, changes, yesterday_stats)

    # 保存 HTML
    os.makedirs(PUBLIC_DIR, exist_ok=True)
    output_path = os.path.join(PUBLIC_DIR, 'index.html')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"Dashboard generated: {output_path}")
    print(f"Total issues: {len(all_issues)}")

    # 保存今天的快照
    save_snapshot(all_issues, today_str)

    # 同时保存统计数据
    stats_path = os.path.join(DATA_DIR, f'{today_str}_stats.json')
    with open(stats_path, 'w', encoding='utf-8') as f:
        json.dump(current_stats, f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
