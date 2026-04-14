# 面向 Python 仓库的函数依赖分析与变更影响评估系统 V1.0
> 开发总文档 / Codex 实施手册 / 软著准备说明
> 版本：1.0
> 日期：2026-04-14
## 0. 本文档怎么用
- 把这份文档放到仓库 `docs/PROJECT_SPEC.md`，作为项目唯一总说明。
- 把附录中的 `AGENTS.md` 模板落到仓库根目录，作为 Codex 的持续约束。
- 开发时按“阶段实施路径”逐段推进，不要让 Codex 一次性生成全量系统。
- 每完成一个阶段，都要求 Codex：列出计划、修改代码、运行测试、同步文档、说明已知限制。
- 本文档同时兼顾软著准备，因此从开发第一周起就要同步积累设计说明、用户手册和源程序页。
## 1. 项目总览
- **一句话定义**：给定一个 Python 代码仓库和一次代码变更，系统自动输出可能受影响的文件、函数和测试，并给出解释路径与风险评分。
- **项目价值**：它不是单纯的“代码搜索器”，而是一个把变更、依赖、测试和解释拼成工程工作流的产品。
- **首发边界**：V1 只支持 Python 仓库；不做多语言，不做深层数据流分析，不承诺处理所有动态特性。
- **适合软著的原因**：边界清楚、模块完整、既有代码又有文档，且可以明确区分第三方依赖与自研核心。
## 2. 项目目标与非目标
### 2.1 核心目标
- 支持接入真实 Python Git 仓库。
- 支持根据工作区 diff、提交区间或两个 ref 发起分析。
- 支持抽取模块/类/函数/测试等对象并建立基础依赖图。
- 支持把变更行号映射到语义对象。
- 支持输出受影响对象、分数、置信度和解释路径。
- 支持导出分析报告与保留任务历史。
- 支持形成软著所需的设计说明、用户手册和代码材料。
### 2.2 明确非目标
- 不支持 Java/Go/TypeScript 等其他语言。
- 不实现 CodeQL/Joern 级的全局程序分析。
- 不做 IDE 插件首发版。
- 不承诺对 `eval`、动态导入、运行时 monkey patch、框架魔法做全覆盖。
## 3. 用户角色与使用场景
- **个人开发者**：提交前快速检查“这次改动可能影响到哪里”。
- **课程/竞赛团队**：合并前补跑高风险测试，减少回归。
- **实验室/科研代码维护者**：面对不熟悉仓库时快速看懂变更影响面。
典型流程：选择项目 → 选择 base/head 或工作区改动 → 系统扫描并分析 → 查看受影响对象与路径解释 → 导出报告/补跑测试。
## 4. 系统架构
```text
Web UI
  -> API 层（FastAPI）
    -> 任务编排层
      -> 仓库接入 / Git diff / 静态解析 / 图构建 / 变更映射 / 影响评估 / 报告导出
        -> SQLite + 文件缓存
```
推荐技术栈：
- 后端：Python 3.11+、FastAPI、Pydantic、SQLAlchemy/SQLModel、pytest、ruff
- 分析：ast、symtable、networkx、pygit2、coverage.py
- 前端：React + TypeScript + Vite（或 Vue 也可，但全项目只选一种）
- 存储：SQLite（V1 足够），报告文件可写入本地目录
- 部署：Docker Compose + 本地开发脚本
## 5. 功能清单
- **仓库接入**：扫描仓库、识别 Python 文件、读取 Git 仓库信息、任务入库
- **静态解析**：抽取模块/类/函数/导入/调用/继承等结构化信息
- **图构建**：构建文件图、符号图、测试关联图及其索引
- **变更映射**：把 diff 的文件、行号和 hunks 映射到语义对象
- **影响评估**：多源图传播、风险评分、置信度分层
- **解释引擎**：输出“为什么命中”的路径与证据
- **测试建议**：给出建议补跑测试与优先级
- **报告导出**：导出 Markdown/HTML/PDF 风格报告（V1 至少支持 Markdown/HTML）
- **任务历史**：保存分析任务、摘要结果、对比信息
- **系统管理**：项目配置、忽略规则、健康检查、帮助页
## 6. 自研边界与复用策略
- **可直接复用**：ast、symtable、pygit2、networkx、coverage.py、pytest、FastAPI、SQLite
- **可选复用**：LibCST（位置信息/源码保真）、grimp（import graph）、pyan3（baseline 调用图）
- **必须自研**：变更映射器、影响传播与评分、解释路径、任务编排、Web 工作台、报告导出
- **不建议 V1 自研**：多语言 parser、通用 LSP、研究级数据流分析、图数据库基础设施
原则：第三方依赖只做底座，系统价值要落在“变更映射 + 影响评分 + 解释路径 + 工作台”四件事上。
## 7. 核心引擎设计
### 7.1 分析流水线
1. 扫描仓库与项目配置。
2. 读取 diff 并拿到 changed files / hunks / line spans。
3. 解析 Python 文件，提取模块、类、函数、导入和定义区间。
4. 构建图：contains、imports、calls、inherits、tests。
5. 将变更行号映射到语义对象（Symbol）。
6. 从 changed symbols 出发做影响传播。
7. 输出受影响对象、分数、置信度和理由。
8. 生成报告并保存历史任务。
### 7.2 变更映射器（必须自研）
- 输入：文件路径、hunk、起止行、修改类型。
- 输出：changed_files、changed_symbols、unmapped_spans。
- 规则：优先映射函数/方法；其次映射类；否则回落到模块/文件级。
- 若变更只落在 import、常量、模块级初始化，也要允许模块级命中。
### 7.3 影响评估器（必须自研）
- 高置信度边：direct call、direct import、direct inherit、direct test link。
- 启发式边：同包近邻、同文件近邻、名字相似、公共入口层级扩散。
- 分数建议：`score = seed_weight + edge_weight * path_decay + optional_test_bonus`。
- 结果必须区分 `high_confidence` 与 `heuristic`。
### 7.4 解释引擎（必须自研）
- 每个高风险结果至少给出一条路径，例如：`service.bootstrap -> api.startup -> tests/test_api.py::test_startup`。
- reasons_json 至少包含：`edge_types`、`source_symbol`、`path_length`、`evidence`。
- 前端需要支持点击展开路径明细。
### 7.5 测试建议（推荐实现）
- V1 可以先基于历史映射和启发式命中；若有 coverage 数据，再做更高置信度推荐。
- 当 coverage 不存在时，要显式提示“当前建议不含动态覆盖证据”。
## 8. 数据模型
- **Project**：name, repo_path, main_branch, language, created_at
- **AnalysisTask**：project_id, diff_mode, base_ref, head_ref, status, started_at, finished_at
- **CodeFile**：project_id, path, module_name, hash
- **Symbol**：file_id, type(module/class/function/test), qualname, start_line, end_line
- **Edge**：src_symbol_id, dst_symbol_id, edge_type, weight, evidence
- **ChangeSpan**：task_id, file_id, hunk_id, start_line, end_line, mapped_symbol_id
- **ImpactResult**：task_id, symbol_id, score, confidence, reasons_json
- **TestSuggestion**：task_id, symbol_id, test_symbol_id, reason, priority
- **ProjectSetting**：project_id, ignore_paths, score_weights, parser_options
## 9. API 设计
- `POST /api/projects`：创建项目记录并绑定本地仓库路径
- `GET /api/projects/{id}`：获取项目基础信息与最近分析结果摘要
- `POST /api/analyses`：发起一次分析任务（支持 diff 模式、提交区间、忽略规则）
- `GET /api/analyses/{id}`：获取分析概览、状态、耗时、统计信息
- `GET /api/analyses/{id}/nodes`：返回受影响对象与评分
- `GET /api/analyses/{id}/paths`：返回解释路径与命中证据
- `GET /api/analyses/{id}/graph`：返回图谱数据给前端可视化
- `GET /api/analyses/{id}/tests`：返回建议补跑测试与原因
- `GET /api/analyses/{id}/report.md`：导出 Markdown 报告
- `GET /api/history`：查询历史任务与筛选条件
- `POST /api/settings`：保存项目级配置、阈值、忽略规则
- `GET /api/health`：健康检查与版本信息
## 10. 前端页面设计
- **项目列表页**：创建项目、查看仓库、查看最近任务
- **分析发起页**：选择 base/head、扫描范围、忽略规则、阈值
- **分析结果概览页**：改动摘要、受影响对象统计、风险分布
- **受影响对象页**：按文件/函数/测试查看、排序、筛选
- **路径解释页**：展示命中链路、边类型、证据
- **图谱页**：节点关系图、路径高亮、点击联动
- **测试建议页**：建议补跑测试、优先级、覆盖证据
- **历史任务页**：查看过往任务、对比变化
- **系统设置页**：阈值、忽略规则、路径白名单/黑名单
- **帮助页**：支持范围、已知限制、使用建议、版本
设计原则：先做“信息层次清楚”，再做“图形炫酷”。V1 图谱页宁可简单，也要保证节点与路径可点、可筛、可回溯。
## 11. 推荐仓库结构
```text
repo-root/
  AGENTS.md
  README.md
  docker-compose.yml
  .env.example
  backend/
    app/
      api/
      analyzers/
      services/
      repositories/
      models/
      schemas/
      core/
    tests/
  frontend/
    src/
      pages/
      components/
      lib/
      api/
  docs/
    PROJECT_SPEC.md
    USER_MANUAL.md
    SOFTCOPY_PREP.md
    ADR/
  fixtures/
    sample_repo_1/
    sample_diffs/
```
## 12. 实施路径（强烈建议按阶段推进）
- **M0 项目启动**：初始化仓库、写 AGENTS.md、搭 FastAPI + React 基架、接 CI
- **M1 仓库接入**：上传/选择本地仓库、保存任务、扫描 Python 文件
- **M2 静态解析**：解析模块/类/函数/导入，建立符号索引
- **M3 图构建**：建立 import / contains / calls / inherits 基础边
- **M4 变更映射**：支持 commit 区间或工作区 diff 映射到文件/符号
- **M5 影响评分**：输出受影响对象、分数、解释路径
- **M6 测试建议**：接 coverage/pytest 元数据，给出补测建议
- **M7 前端工作台**：任务列表、详情页、图谱页、报告页
- **M8 测试与文档**：单测、集成测试、性能基线、部署文档、用户手册
- **M9 软著收口**：整理源程序页、说明书、操作手册、权属材料
阶段原则：
- 一次只做一个阶段。
- 每阶段都必须有测试和文档。
- 每阶段都要能独立演示。
## 13. 测试与验收
### 13.1 测试层次
- 单元测试：解析器、图构建、变更映射、评分器。
- 集成测试：给定 fixture 仓库和 diff，校验输出的受影响对象与路径。
- API 测试：核心接口成功态、失败态、空数据态。
- 前端测试：关键页面加载、空态、错误态、筛选逻辑。
### 13.2 验收标准
- 能在一份中小型 Python 仓库上跑通完整流程。
- 至少有 3 套 fixture：纯函数仓库、类方法仓库、含 tests 仓库。
- 高风险结果均可解释。
- 无 coverage 时能优雅降级。
- README、用户手册、部署说明可独立让他人复现。
## 14. Codex 使用方法（本项目最关键的一章）
### 14.1 工作原则
- 不要让 Codex 一次生成“完整系统”。
- 要把任务拆成小阶段，并在每次 prompt 中给出目标、上下文、约束和完成标准。
- 每次修改前后都打 Git checkpoint。
- 关键模块（评分、解释、权属材料）必须人工复核。
### 14.2 通用母提示词
```text
你现在在实现项目《面向 Python 仓库的函数依赖分析与变更影响评估系统 V1.0》。

Goal
- 完成 <本阶段目标>

Context
- 项目说明见 docs/PROJECT_SPEC.md
- 当前相关目录：<列出目录>
- 当前相关文件：<列出文件>
- 参考数据或错误日志：<列出>

Constraints
- 仅支持 Python 仓库，不要扩展多语言
- 优先使用标准库 ast / symtable 与现有依赖，不要引入重量级新框架
- 改动必须保持现有目录结构清晰，禁止把所有逻辑写进单文件
- 新增或修改的功能必须附带测试
- 返回结果必须可解释，不能只输出黑盒分数

Done when
- 代码可运行
- 相关测试通过
- 文档已同步更新
- 输出中明确列出变更文件、实现思路、测试结果、已知限制

请先给出实施计划，再分步修改代码；完成后总结风险与后续建议。
```
### 14.3 AGENTS.md 模板
```markdown
# AGENTS.md

## Project identity
- Project: Python repo change-impact analyzer
- Primary goal: map code changes to impacted symbols and tests with explanations
- Stage: V1 only, Python-only

## Non-goals
- No multi-language support
- No deep interprocedural data-flow engine
- No IDE/LSP replacement
- No hidden background services without explicit need

## Working agreements
- Read docs/PROJECT_SPEC.md before changing code
- Keep modules small and single-purpose
- Prefer explicit types and dataclasses / pydantic models where appropriate
- Do not introduce new production dependencies unless clearly justified in the task result
- Always update tests when behavior changes
- Always update docs when APIs or data contracts change
- Keep all user-facing scoring output explainable

## Architecture rules
- backend/app/api: HTTP endpoints and request/response schemas only
- backend/app/services: orchestration only
- backend/app/analyzers: parsing, graph building, diff mapping, scoring
- backend/app/repositories: persistence access only
- backend/app/models: ORM and domain models
- frontend/src/pages: route-level views
- frontend/src/components: reusable UI blocks
- docs/: specifications, ADRs, user manual, soft-copy-prep notes

## Code quality
- Python: use ruff + pytest; add mypy-friendly annotations where reasonable
- Frontend: keep components focused and typed
- Never swallow exceptions silently
- Return structured errors with human-readable messages

## Verification
- For backend changes run: pytest
- For parser/graph/scoring changes add focused fixture tests
- For API changes update OpenAPI docs or response models
- For frontend changes verify key pages render and empty/error states work

## Definition of done
- Code compiles/runs
- Relevant tests pass
- New behavior is documented
- Known limitations are stated explicitly
- Final output includes changed files, why they changed, and what remains risky

```
### 14.4 分阶段 prompt 包
#### P0 初始化工程
```text
根据 docs/PROJECT_SPEC.md 初始化仓库：创建 backend/frontend/docs 目录、FastAPI 与 React 基础工程、pytest 与基础 CI、README、AGENTS.md。不要实现业务逻辑，只完成骨架与运行脚本。
```
#### P1 仓库接入
```text
实现项目创建与仓库扫描：输入本地仓库路径，识别 Python 文件并持久化项目与文件记录。为非法路径、非 Git 仓库、空仓库写测试。
```
#### P2 AST 解析
```text
实现 Python 静态解析器：抽取模块、类、函数、导入、定义区间。使用 ast 和 symtable；先做准确的数据结构与单测，不做复杂调用图。
```
#### P3 图构建
```text
在现有解析结果上构建 contains/import/calls/inherits 四类边。先确保图结构可查询、可序列化，再补 API。
```
#### P4 变更映射
```text
实现 Git diff 到文件和符号的映射。支持 base_ref/head_ref，输出 changed_files、changed_symbols、unmapped_spans。补充 rename 与新增文件的行为说明。
```
#### P5 影响评分
```text
实现影响传播与评分：区分高置信度与启发式命中；每个结果都要包含 reasons_json 和最短解释路径。为评分规则写 fixtures。
```
#### P6 测试建议
```text
接入 coverage/pytest 产物或历史映射，输出建议补跑测试列表。没有 coverage 数据时，返回降级策略并说明原因。
```
#### P7 前端工作台
```text
实现任务列表、分析结果概览、受影响对象页、路径解释页。优先保证信息层次清晰，而不是追求花哨视觉。
```
#### P8 文档与收口
```text
补齐用户手册、部署说明、设计说明书摘要、API 示例与软著准备说明；检查 README、docs、测试、示例数据是否齐全。
```
## 15. 工程与权属风险控制
- **项目范围失控**：风险来源是“同时追求多语言、深层数据流、IDE 级能力”；控制措施是“只做 Python；把“精确导航”与“影响评估”分开；V1 不做多语言”。
- **结果解释性差**：风险来源是“只给出列表，不给命中原因”；控制措施是“所有高风险结果必须输出路径和证据”。
- **像拼装品**：风险来源是“直接 fork 现成项目换名”；控制措施是“第三方全部走依赖；核心模块自研；保留 Git 开发证据”。
- **权属不清**：风险来源是“学校/实验室/雇佣关系下开发却未明确归属”；控制措施是“提交前先确认个人、团队、导师或单位的权利边界”。
- **软著材料不足**：风险来源是“代码页数、文档页数、说明书不够规范”；控制措施是“从 M4 起同步积累说明书、流程图、操作手册”。
再加三条硬约束：
- 所有第三方库都走依赖管理，不大段 vendoring 进主仓。
- 保留 Git 历史、设计稿、测试记录。
- 若项目涉及学校、导师、实验室、雇佣或合作开发，先确认权利归属再申请登记。
## 16. 软著准备方案
### 16.1 建议的软件名称
- 正式名称：**面向 Python 仓库的函数依赖分析与变更影响评估系统 V1.0**
- 内部代号：B-Impact
- 英文可选：Python Repository Change Impact Analysis System
### 16.2 建议准备的文档
- 软件设计说明书
- 用户操作手册
- 部署说明
- 测试报告
- 权属说明（必要时）
- 第三方依赖清单及许可说明
### 16.3 代码交存策略
- 优先选自研核心模块：`diff_mapper.py`、`graph_builder.py`、`impact_scorer.py`、`explain_service.py`、关键 API 与前端结果页。
- 不要让大量第三方库包装层占满交存页。
- 代码交存页优先体现“系统核心能力”，而不是样板脚手架。
### 16.4 申请步骤（按当前官方流程理解）
- 在中国版权保护中心著作权登记系统注册并实名认证。
- 在线填报软件著作权登记申请。
- 打印申请确认签章页，签章后按要求上传 PDF。
- 等待受理、补正、审查。
- 审查通过后下载电子证书。
### 16.5 提前准备清单
- 软件名称与简称
- 版本号
- 开发完成日期
- 主要功能简介（约 150–300 字可反复打磨）
- 技术特点（不要吹成研究级平台）
- 申请人身份材料
- 必要时的合同、任务书、许可证明
## 17. 项目最终交付物
- 可运行源码仓库
- 完整 README
- AGENTS.md
- docs/PROJECT_SPEC.md
- 用户手册
- 部署说明
- 测试报告
- 软著准备材料包
- 一组可演示的 fixture 仓库与样例 diff
## 18. 你现在就该做的三件事
1. 把本文档存入 `docs/PROJECT_SPEC.md`。
2. 把附录中的 `AGENTS.md` 落到仓库根目录。
3. 用 P0 初始化 prompt 让 Codex 先搭工程，不要直接上业务内核。
## 19. 附录：参考依据
- OpenAI Developers / Codex overview
- OpenAI Developers / Codex best practices
- OpenAI Developers / Codex prompting, quickstart, AGENTS.md guidance
- 国家版权局 / 计算机软件著作权登记办法
- 中国版权保护中心 / 计算机软件著作权登记指南、办理步骤与电子证书说明
- 中国政府网 / 计算机软件保护条例
- OpenAI Terms of Use / Services Agreement（输入输出归属与相似输出说明）
