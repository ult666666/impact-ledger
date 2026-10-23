# Impact Ledger 简明指南

这是一个本地运行的公益项目运营数据演示。**所有示例记录均为合成数据**，不代表任何真实机构、服务对象或实际成效。请勿导入真实个人信息。

需要 Python 3.11 及以上版本。前端已编译，无需 Node 即可启动：

```sh
python3 -m impact_ledger --db .local/demo.db seed
python3 -m impact_ledger --db .local/demo.db serve
```

打开 http://127.0.0.1:8765 。服务仅监听本机地址。使用 Ctrl-C 停止。`seed` 仅能写入空数据库；重复演示时请换一个数据库路径。

- 日期筛选包含起止日期；项目名称按原文精确匹配。点击 Apply filters 后，统计、图表、表格和导出使用同一范围。
- Unique participants：所选活动中不同参与者 ID 的数量。一个人参加多场活动仍只计算一次。
- Attendance：一人参加一场活动记一次。同一人同一场不可重复。
- Participant hours：每场活动时长乘以出席人数，假设每人参加全程。
- Actual spending：按活动计算实际支出，不随出席人数重复累计。
- Variance = 实际支出 − 预算。正数表示超支；百分比以预算为分母，预算为零时不显示百分比。

出席和支出仅描述活动与覆盖范围，**不能证明项目效果或因果影响**。不同项目或月份的独立人数可能重叠，不应直接相加。

CSV 导入先导入活动，再导入出席记录。表头顺序必须完全一致：

```csv
session_id,program,session_date,duration_hours,budget,actual
```

```csv
attendance_id,session_id,participant_id
```

日期格式为 `YYYY-MM-DD`。金额单位为美元，金额与小时最多两位小数。负数、非有限数、重复 ID、不存在的活动引用、错误日期等会导致**整个文件回滚**，不会部分导入。每份文件最多 1 MiB、5,000 行。项目名支持中文；ID 使用英文字母、数字、点、下划线或短横线。

```sh
python3 -m impact_ledger --db .local/example.db import sessions examples/sessions.csv
python3 -m impact_ledger --db .local/example.db import attendance examples/attendance.csv
python3 -m impact_ledger --db .local/example.db summary --program '社区服务'
```

开发与测试需要 Node 24+：

```sh
npm ci --ignore-scripts
python3 -m unittest discover -s tests -v
npm run typecheck
npm run build
npm test
npx playwright install chromium
npm run test:browser
```

构建后的 `site/` 是只读静态演示。它支持筛选和 CSV 导出，明确禁用导入；修改 SQLite 数据需要运行本地服务。该项目没有登录、权限管理、审计历史、备份管理或生产环境安全保障。请勿公开部署 Python 写入服务。

初始实现使用了 AI 辅助开发，并通过自动化计算、真实 HTTP、浏览器交互和视觉检查；具体范围见 [验证记录](VERIFICATION.md)。完整定义见 [数据字典](DATA_DICTIONARY.md)。
