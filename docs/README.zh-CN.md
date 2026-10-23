# Impact Ledger 简明指南

这是一个本地运行的公益项目运营数据演示。**所有示例记录均为合成数据**，不代表任何真实机构、服务对象或实际成效。请勿导入真实个人信息。

需要 Python 3.11 及以上版本。前端已编译，无需 Node 即可启动：

```sh
python3 -m impact_ledger --db .local/demo.db seed
python3 -m impact_ledger --db .local/demo.db serve
```

打开 http://127.0.0.1:8765 。服务仅监听本机地址。使用 Ctrl-C 停止。`seed` 仅能写入空数据库；重复演示时请换一个数据库路径。

- 日期筛选包含起止日期；项目名称按原文精确匹配。点击 Apply filters 后，统计、图表、表格和导出使用同一范围。
- 勾选 Compare prior period，使用**已应用**的起止日期和同一项目，对比紧邻的等天数前期。必须明确填写两个日期并点击 Apply filters；缺失日期会显示操作提示。2026-09-01 至 2026-09-30 对比 2026-08-02 至 2026-08-31，并非整个上月。日期计算不受夏令时影响；前期早于公元 0001 年时会拒绝。
- 对比表列出两个期间的总数和“本期 − 前期”差值。每个期间独立去重，同一人可能在两个期间出现。空期间显示零；不计算环比百分比，原有比率分母为零时仍为 null。较低的预算差额本身不能证明改善或因果效果。
- 点击 Print report 可打印或用浏览器保存 PDF：包含合成数据声明、已应用筛选、八项本期总数、图表、完整表格和已开启的对比；隐藏按钮与导入表单。导入成功后按最新提交的筛选刷新对比，即使该筛选请求仍在加载；未提交的表单修改不生效。当前视图、导入刷新或已开启的对比仍在加载时，Print report 按钮会禁用并显示原因；视图加载失败时继续禁用。对比已完成但不可用时，可打印本期数据，报告会明确包含“Comparison unavailable”及具体原因。
- Unique participants：所选活动中不同参与者 ID 的数量。一个人参加多场活动仍只计算一次。
- Attendance：一人参加一场活动记一次。同一人同一场不可重复。
- Participant hours：每场活动时长乘以出席人数，假设每人参加全程。
- Actual spending：按活动计算实际支出，不随出席人数重复累计。
- Variance = 实际支出 − 预算。正数表示超支；百分比以预算为分母，预算为零时不显示百分比。

出席和支出仅描述活动与覆盖范围，**不能证明项目效果或因果影响**。不同项目或月份的独立人数可能重叠，不应直接相加。

可先点击 **Preview CSV**，按 CSV 行号、列名和修复提示检查错误；这是可选步骤，预览不会新增记录或占用 ID。更换文件或记录类型会清除旧结果；同名文件的新内容也必须重新检查。最多显示 100 条错误。预览仅反映当时数据库状态，点击 **Import CSV** 后仍会重新校验当前文件与数据库；其他导入可能导致原本有效的预览在正式导入时被整体拒绝。

CSV 导入先导入活动，再导入出席记录。表头顺序必须完全一致：

```csv
session_id,program,session_date,duration_hours,budget,actual
```

```csv
attendance_id,session_id,participant_id
```

日期格式为 `YYYY-MM-DD`。金额单位为美元，金额与小时最多两位小数。负数、非有限数、重复 ID、不存在的活动引用、错误日期等会导致**整个文件回滚**，不会部分导入。每份文件最多 1 MiB、5,000 行。项目名支持中文；ID 使用英文字母、数字、点、下划线或短横线。

```sh
python3 -m impact_ledger --db .local/example.db init
python3 -m impact_ledger --db .local/example.db preview-import sessions examples/sessions.csv
python3 -m impact_ledger --db .local/example.db import sessions examples/sessions.csv
python3 -m impact_ledger --db .local/example.db import attendance examples/attendance.csv
python3 -m impact_ledger --db .local/example.db summary --program '社区服务'
python3 -m impact_ledger --db .local/demo.db comparison --start 2026-09-01 --end 2026-09-30 --program 'Learning Lab'
```

`preview-import` 输出 JSON：有效时退出码 0，CSV 校验问题为 1，用法、文件或数据库错误为 2。必须先有已初始化的数据库；预览不会创建不存在的数据库路径或初始化空文件。API 与错误代码见 [接口说明](API.md)。

开发与测试需要 Node 24+：

```sh
npm ci --ignore-scripts
python3 -m unittest discover -s tests -v
npm run typecheck
npm run build
npm test
npx playwright install chromium
npm run test:browser
python3 scripts/build_site.py --verify-only
```

构建后的 `site/` 是只读静态演示。它支持筛选和 CSV 导出，明确禁用 CSV 校验预览与导入；检查数据库 ID、活动引用或修改 SQLite 数据需要运行本地 API 服务，不会把静态演示当作数据库校验。该项目没有登录、权限管理、审计历史、备份管理或生产环境安全保障。请勿公开部署 Python 写入服务。

静态输出严格限定为七个普通文件：`index.html`、`app.js`、`model.js`、`styles.css`、`favicon.svg`、合成快照 `demo.json` 和空的 `.nojekyll`。可用 `python3 scripts/build_site.py --output-directory '/tmp/impact preview'` 单独构建，父目录必须已存在。路径中包括 `..` 前的每个父级组件也必须实际存在，不能通过折叠缺失目录绕过检查。构建前拒绝目标目录自身的符号链接、源码与输出重叠、任何未知文件/目录，以及已知名称的符号链接或非普通文件；失败前不会修改目标。已有输出可重新构建并修复缺失或被修改的普通生成文件。未知内容需由文件所有者自行移走，没有强制删除选项。可信父目录的别名会规范化解析，目标自身仍不能是符号链接。

加上 `--verify-only` 会逐字节核对实际输出，不创建、修复或重写目标。成功输出含七个文件字节数和 SHA-256 的有界 JSON；失败只给出稳定代码及已知文件名，不显示未知名称、私有内容或异常路径。退出码为 0（完全匹配）、1（边界/内容/I/O 问题）、2（参数用法错误）。为计算预期值，会在单独的临时 SQLite 数据库生成合成数据；只读承诺针对所选目标，读取仍可能更新访问时间。构建使用私有临时文件并逐个原子替换，避免通过硬链接覆盖其他文件；普通失败会清理自己的临时文件，但不保证整个目录原子更新，也不防御并发路径篡改或断电。发布前必须完成最终校验。

现在只有一个 CI/Pages 工作流：Python 3.11/3.13 完整与安装测试，以及 Node24 构建、模型和真实 Chromium 测试；浏览器测试后校验同一 `site/`，再仅在非 PR 的 main 分支上传。部署同时依赖 Python 和前端成功，只使用本次运行已测试的产物。PR 和非 main 的手动运行执行完整测试并跳过发布；只有受保护的部署任务拥有 Pages/token 写权限。并发按 ref 区分，非 main 运行不会取消 main。任务使用明确的 Ubuntu24.04、固定 action、15 分钟超时；截图产物保留七天。发布内容不包含 Python、数据库、CSV 导入文件、依赖、wheel 或本地报告。

初始实现使用了 AI 辅助开发，并通过自动化计算、真实 HTTP、浏览器交互和视觉检查；具体范围见 [验证记录](VERIFICATION.md)。完整定义见 [数据字典](DATA_DICTIONARY.md)。
