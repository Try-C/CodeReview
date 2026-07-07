# CodeReview Agent 大厂面试问答

> 基于真实项目经历，涵盖架构设计、AI/LLM、RAG、数据库、可靠性、测试等方向。  
> 适用岗位：后端开发、AI 应用开发、全栈开发。

---

## 一、项目概述（必问）

### Q1：简单介绍一下这个项目

**答：** CodeReview Agent 是一个面向 Java/Python 的 AI 代码审查平台。核心思路是：**不能把整个仓库直接丢给 LLM**——Token 超限、上下文稀释、模型幻觉都会导致审查质量不可控。

我的方案分四层：
1. **解析层**：用 Tree-sitter 将源码解析为带路径、符号、行号的语义代码块，而不是简单按行切割。
2. **检索层**：构建 Hybrid RAG——pgvector 向量检索 + PostgreSQL 全文检索 + RRF 融合，从大仓库中精准召回审查目标相关的代码上下文。
3. **审查层**：LangGraph 编排 Planner → Reviewer → EvidenceVerify → Critic 工作流。**证据校验在 Critic 之前**，用确定性代码验证模型输出的文件路径、行号、证据文本是否真实存在。
4. **报告层**：生成可定位到真实代码行、附带证据、原因、修复建议的 Markdown 报告。

技术栈：Python 3.12 + FastAPI + LangGraph + PostgreSQL/pgvector + Redis + Vue 3。

---

### Q2：这个项目解决了什么问题？为什么要做？

**答：** 三个核心痛点：
1. **大仓库无法整包交给模型**：62 个 Java 文件、2837 行代码，直接拼接 Token 就爆了，且大量无关代码会稀释模型注意力。Hybrid RAG 把上下文窗口聚焦到真正相关的 ~10 个代码块。
2. **LLM 会"幻觉"**：模型经常虚构文件路径、编造行号、声称漏洞但拿不出证据。EvidenceVerify 四道确定性校验在 Critic 之前拦截这些幻觉。
3. **成本与质量不可度量**：Benchmark + 消融实验 + 每次 LLM 调用保存价格快照，Precision/Recall/F1/Token/成本全部可量化。

---

## 二、架构设计

### Q3：为什么用 LangGraph 而不是自己写状态机或直接用 LangChain Agent？

**答：** 

- **不用 LangChain AgentExecutor**：它内部有隐式的 Agent 循环，很难精确控制"什么时候该停"，我们需要明确的预算上限。
- **不用自己写状态机**：LangGraph 提供了图编译、条件路由、`recursion_limit` 保护、流式状态输出这些能力，比自己维护状态转换表更可靠。
- **LangGraph 的边界很清晰**：我只用它的 StateGraph、条件边和 `astream`。Prompt 管理、模型调用、结构化输出解析、检索逻辑全部自己封装，不依赖 LangChain 的高级抽象。

核心代码结构：
```python
builder = StateGraph(CodeReviewState)
builder.add_node("planner", recorded(PlannerAgent(structured_llm)))
builder.add_node("review", recorded(ReviewerAgent(structured_llm)))
builder.add_node("critic", recorded(CriticAgent(structured_llm)))
builder.add_node("evidence_verify", EvidenceVerifyNode(verify_fn))
builder.add_conditional_edges("review_decision", route_review_decision, {
    "advance_item": "advance_item",
    "rewrite_query": "rewrite_query",
    "evidence_verify": "evidence_verify",
})
result = await graph.astream(initial_state, config={"recursion_limit": 300})
```

---

### Q4：为什么要做 EvidenceVerify 而不直接让 Critic 做？

**答：** 这是整个项目最重要的设计决策之一。

**确定性代码 vs 概率性模型的边界**：
- EvidenceVerify 做的是**客观事实校验**：文件是否存在？行号是否在范围内？证据文本是否匹配？这些 LLM 做不到 100% 准确，但代码可以。
- Critic 做的是**语义判断**：这个 SQL 注入的严重程度是否合理？修复建议是否可行？这些需要模型的理解能力。

**为什么不让 Critic 一起做？** 因为 LLM 对"这项证据是否真的存在"这种问题的准确率远不如确定性代码。我曾经遇到过模型说"文件第 45 行存在 SQL 注入"，但实际文件只有 30 行——这种错误 Critic 也未必能发现。EvidenceVerify 在 Critic 之前拦截，既减少了无效的 LLM 调用，又提高了最终报告的准确性。

消融实验结果也证明了这一点：Review + Evidence + Critic 的 Macro F1 是 0.769，而 Review + Critic 只有 0.667。

---

### Q5：为什么用进程内 TaskRunner 而不是 Celery？

**答：** Celery 在 Windows 上存在严重的稳定性问题——prefork pool 在 Windows 上不可用，solo pool 的 worker 进程会静默崩溃，导致任务在 Redis 队列中永远等待。

我的方案是：
1. FastAPI 启动时在 `lifespan` 中启动 `TaskRunner` 协程
2. TaskRunner 每 3 秒轮询数据库 `SELECT ... FOR UPDATE SKIP LOCKED` 获取 pending 任务
3. 在同一进程中执行审查管道

**设计考量：**
- 原子认领：`FOR UPDATE SKIP LOCKED` 保证多进程安全
- 状态解耦：通过数据库 `status` 字段驱动，不依赖消息队列的可靠性
- 可切换：保留了 `TaskDispatcher` 接口，生产环境可切回 Celery 获得独立扩缩容

---

### Q6：检索模块为什么要用 Hybrid RAG（向量 + 全文 + RRF）？

**答：** 纯粹的向量检索对代码场景有天然的盲区：

- **精确匹配场景**：搜索 `SQLException`、`@Transactional` 这种确切 API 名，全文检索比向量更准。
- **语义场景**：搜索"数据库事务处理不当"，向量检索能理解语义。
- **RRF 融合**：`score = 1/(K+vector_rank) + 1/(K+keyword_rank)`，两路互相补充。

消融实验验证：Keyword-only F1=0.333，Vector-only F1=0.462，Hybrid RRF F1=0.625。

另外设计了完整的降级链：Embedding 失败 → keyword_only；向量检索失败 → 全文 → ILIKE 符号名兜底。任何单点故障都不会让检索完全不可用。

---

## 三、AI / LLM 深度问题

### Q7：LLM 输出的结构化解析是怎么做的？JSON 格式不稳定怎么办？

**答：** 三层防护：

1. **json_mode**：DeepSeek API 支持 `response_format={"type": "json_object"}`，告诉模型输出 JSON。
2. **extract_json**：从响应中提取 JSON——处理模型包裹 markdown code fence 或前缀文本的情况，找最外层的 `{}` 或 `[]`。
3. **Pydantic 校验 + 一次修复重试**：解析失败时，把错误信息附到对话中再请求一次。两次都失败则抛出 `StructuredOutputError`，Agent 节点捕获后返回 fallback 状态。

```python
# 第一次尝试
parsed = self._parse_with_repair(result.content, response_model)
if parsed is not None:
    return parsed, result

# 修复重试
repair_messages = [*messages, {"role": "assistant", "content": result.content},
    {"role": "user", "content": "Your previous response was not valid JSON..."}]
result2 = await self._client.chat(repair_messages, json_mode=True)
parsed = self._parse_with_repair(result2.content, response_model)
if parsed is not None:
    return parsed, combine_call_results(result, result2)

raise StructuredOutputError("Failed after 2 attempts", result=combined)
```

**额外校验**：`IssueCandidate` 有 Pydantic `model_validator`——security 分类必须有 `cwe_id`，`end_line >= start_line`，`confidence` 在 0-1 之间。这些规则不依赖模型自觉。

---

### Q8：怎么防止 LLM 调用次数失控？

**答：** 四层限制：

1. **BudgetGuard × 4**：Planner、Retrieve、Review、Critic 前各有一个 Guard，检查 `cancel_requested | llm_call_count >= MAX_LLM_CALLS | tokens >= MAX_TOKEN_BUDGET`。超限直接路由到 Report。
2. **LANGGRAPH_RECURSION_LIMIT=300**：图节点执行次数的硬上限，作为最后保险。
3. **MAX_REVIEW_ROUNDS=2**：Critic 失败的重审次数限制。
4. **MAX_RETRIEVAL_RETRIES=2**：上下文不足的重检索次数限制。

所有限制触发后都优雅降级为 `partial_success`，保留已完成结果，不会让用户等待后得到"失败"。

实际运行数据：62 文件项目消耗 21 次 LLM 调用、60K input tokens、27K output tokens。成本完全可预测。

---

### Q9：你是怎么处理模型成本的？

**答：** 三个原则：

1. **Decimal 计算**：金额全部用 `Decimal`，禁止浮点。`cost = (input_tokens * price_per_million + output_tokens * price_per_million) / 1_000_000`，精度到百万分之一。
2. **价格快照**：每次 LLM 调用在 `NodeRun` 中保存 `model_name`、`pricing_version`、`input_price_per_million`、`output_price_per_million`。未来供应商调价不影响历史成本。
3. **价格从配置来，不硬编码**：`LLM_INPUT_PRICE_PER_MILLION` 和 `LLM_PRICING_VERSION` 通过环境变量配置。价格未配置时显示 `cost_unavailable`，不静默记为 0。

---

### Q10：Agent 工作流中 State 是怎么设计的？

**答：** `CodeReviewState` 是一个 Pydantic `BaseModel`，包含所有可序列化状态：

```python
class CodeReviewState(BaseModel):
    task_id: int
    project_id: int
    review_plan: list          # Planner 输出
    current_review_index: int  # 当前审查到第几项
    verified_issues: list      # 通过所有校验的 issue
    rejected_issues: list      # 被拒绝的 issue
    current_issues: list       # 当前项候选 issue
    retrieved_context: str     # RAG 检索结果
    retrieval_retry_count: int # 重检索计数
    review_round: int          # Critic 重审轮次
    llm_call_count: int        # 累计 LLM 调用
    input_tokens / output_tokens: int
    next_action: str           # 路由信号
    stop_reason: str | None    # 停止原因
    cancel_requested: bool
```

**设计原则：**
- 只存可序列化数据（不存 DB Session、HTTP Client）
- 节点通过返回 `dict` 更新状态，不直接修改
- 条件路由只读 `next_action`，纯函数，无副作用
- `verified_issues` 和 `rejected_issues` 在多个节点间累加，用 fingerprint 去重

---

## 四、数据库与存储

### Q11：为什么选 PostgreSQL + pgvector 而不是专用向量数据库（Milvus、Pinecone）？

**答：** 

1. **减少依赖**：这是单人项目，不需要维护额外的向量数据库服务。pgvector 作为 PostgreSQL 扩展，Docker 镜像直接支持。
2. **事务一致性**：Chunk 和 Embedding 在同一事务中写入，天然保证一致性。专用向量库需要额外处理跨系统事务。
3. **功能完备**：pgvector 0.8.x 已支持 HNSW 索引、IVFFlat、cosine/L2/inner_product 三种距离。本项目使用的 `vector_cosine_ops` + HNSW 在几千个 Chunk 规模下性能足够。
4. **检索与业务数据同库**：`ContextAssembler` 需要 JOIN `code_chunks`、`code_symbols`、`code_relations` 三张表，全在 PostgreSQL 内完成。

如果未来数据量增长到百万级 Chunk，可以考虑将向量索引迁移到专用库，但业务数据和 Trace 继续留在 PostgreSQL。

---

### Q12：怎么保证幂等性？Celery 重试会不会重复生成数据？

**答：** 每张核心表都有数据库级 UNIQUE 约束：

| 表 | 唯一约束 | 作用 |
|---|---------|------|
| `review_tasks` | `(user_id, idempotency_key)` | 同一用户不重复创建任务 |
| `code_chunks` | `(project_id, chunk_fingerprint)` | 同一代码块不重复入库 |
| `code_symbols` | `(project_id, symbol_hash)` | 同一符号不重复 |
| `review_issues` | `(task_id, fingerprint)` | 同一 issue 不重复写入 |
| `node_runs` | `(task_id, run_key)` | 同一节点调用不重复计数 |

`_replace_issues()` 采用 DELETE + INSERT 策略：先删除该任务的所有旧 issue，再写入新 issue。在同一个事务中完成，保证原子性。Python 内存中还有 fingerprint 去重，防止同一批次出现重复。

---

### Q13：`search_vector` 的全文索引是怎么维护的？

**答：** 使用 PostgreSQL Trigger 自动维护：

```sql
CREATE FUNCTION code_chunks_search_vector_update()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector := to_tsvector('simple', COALESCE(NEW.search_text, ''));
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_code_chunks_search_vector
BEFORE INSERT OR UPDATE OF search_text ON code_chunks
FOR EACH ROW EXECUTE FUNCTION code_chunks_search_vector_update();
```

`search_text` 在 Python 层拼接了 `relative_path + symbol_name + qualified_name + 拆分标识符 + imports + content`，Trigger 自动转为 `tsvector`。使用 `simple` 配置而非 `english`，避免代码标识符被错误词干化。标识符如 `findUserByName` 会拆分为 `find user by name`。

---

## 五、可靠性与错误处理

### Q14：项目中遇到过什么 Bug？怎么修复的？

**答：** 报告生成链路出过严重的 bug，任务一直卡在 `failed` 状态。经过完整排查，修复了 10 个 bug：

**最严重的三个：**

1. **`_replace_issues()` 用 `[]` 访问 dict 无默认值**：Issue dict 经过 Reviewer → EvidenceVerify → CriticDecision 四层节点修改后，部分字段可能缺失。`issue["fingerprint"]` 在 key 不存在时抛 `KeyError` → 整个报告持久化崩溃 → 任务 `failed`。修复：全部改用 `issue.get("key", default)`。

2. **向量检索 SQL 语法错误**：`VECTOR_COSINE_SQL` 中使用 `:query_vector::vector`，但 asyncpg 将 `:` 解析为参数占位符，`::vector` 被误认为无效语法。修复：改为 `CAST(:query_vector AS vector)`。

3. **`ReviewReport` 查询用 `session.get(id)` 而非 `task_id`**：`ReviewReport` 的主键是 `id`（自增），不是 `task_id`。API 用 `session.get(ReviewReport, task_id)` 按主键查永远返回 None → 前端 404。修复：改为 `select(ReviewReport).where(ReviewReport.task_id == task_id)`。

**系统性改进：**
- `_persist_result()` 增加 try/except + rollback，防止任何 DB 异常导致任务静默失败
- `_aggregate_usage()` 增加降级逻辑，失败时使用零值 metrics 继续生成报告
- `EvidenceVerifyNode` 异常路径补全 fingerprint 生成，防止 issue 被 `_append_unique()` 静默丢弃

---

### Q15：如果 LLM API 完全挂掉了，系统会怎样？

**答：** 优雅降级，不会崩溃：

1. `LLMClient.chat()` 抛异常 → `StructuredLLM.invoke()` 抛 `StructuredOutputError`
2. Planner Agent 捕获 → 返回 `review_plan: []`, `next_action: "report"`, `stop_reason: "planner_failed"`
3. LangGraph 路由到 Report 节点 → 生成空报告
4. 任务状态：`partial_success`，`fallback_reason: "planner_failed"`
5. 报告的 `summary` 显示 "No issues were identified during this review."

用户看到的是一个完整的报告页面（而不是白屏或 500），报告明确标注 `stop_reason: planner_failed`，用户可以知道发生了什么。

`UnavailableLLMProvider` 是一个专门的占位实现，在 API key 未配置时使用，`chat()` 方法直接抛 `LLMClientError("LLM_PROVIDER_UNAVAILABLE")`，行为和 API 挂掉一致。

---

### Q16：文件上传有什么安全措施？

**答：**

- **路径安全**：拒绝绝对路径、`..`、超长路径（>512字符）和非法字符。使用 `Path.resolve() + relative_to()` 双重验证。
- **链接拒绝**：拒绝符号链接、Windows Reparse Point、设备文件。
- **数量限制**：单文件 ≤3MB，总大小 ≤300MB，文件数 ≤5000，总行数 ≤150000。
- **隔离存储**：上传文件存放在服务端随机生成的 `storage_key` 目录下，不保留用户原始目录结构信息。
- **编码策略**：UTF-8 → UTF-8-SIG → GB18030/GBK → 仍失败则跳过并记录。绝不使用 latin-1 强行"解码成功"。
- **永不执行**：系统不执行、编译、导入任何用户上传的代码。

---

## 六、测试与质量

### Q17：你们的测试策略是什么？

**答：** 三层测试 + Fake Provider 策略：

**单元测试**（66+ 个）：
- 路径安全和文件过滤
- LanguageAdapter 契约、Parser 行号
- RRF、Fingerprint、EvidenceService
- BudgetGuard 分支、所有 LangGraph Route 纯函数
- 成本计算 Decimal 精度和零价格处理
- Security issue 的 CWE 条件校验

**集成测试**（端到端链路）：
- 使用 SQLite (aiosqlite) + FakeLLMClient + FakeEmbeddingProvider
- 完整测试：上传 → 解析 → 索引 → Agent 工作流 → 报告生成
- 验证幂等：同一任务执行两次，`node_runs` 数量不变

**图分支测试**：
- 空 plan → Report、无 issue → 下一项、上下文不足 → 重写 Query
- Evidence 全失败 → advance、Critic 部分通过 → 通过项保留
- Budget 超限 → 不调 LLM、recursion_limit → partial_success

**Fake Provider 策略**：测试中永远不调用付费 API。`FakeLLMClient` 返回预配置的 JSON 响应，`FakeEmbeddingProvider` 返回固定向量。

---

### Q18：怎么保证 LLM 输出质量？

**答：** 不能"保证"LLM 质量，但可以通过系统设计来约束：

1. **Pydantic 强制校验**：所有 LLM 输出必须通过 Schema 校验，不合格的重试一次，再不合格丢弃。
2. **EvidenceVerify 拦截幻觉**：文件路径、行号、证据文本必须真实存在。
3. **Critic 复核**：对通过证据校验的 issue 做语义二次判断。
4. **Benchmark 度量**：Precision/Recall/F1 量化模型效果，消融实验归因每个模块的贡献。

---

## 七、系统设计思维

### Q19：如果要支持 100 个并发审查任务，你会怎么改造？

**答：**

1. **任务队列**：当前 TaskRunner 是单进程轮询。高并发时换回 Celery + Redis，多个 Worker 进程独立拉取任务。
2. **数据库连接池**：配置合理的连接池大小，使用 PgBouncer 做连接复用。
3. **LLM API 限流**：DeepSeek API 有并发限制。在 LLMClient 层加 asyncio.Semaphore 或令牌桶限流器。
4. **Embedding 缓存**：相同内容的 Chunk 复用已有 Embedding（已实现 `content_hash` 去重）。
5. **图状态持久化**：LangGraph 支持 checkpoint，任务可暂停和恢复，避免长时间占用 Worker。
6. **检索加速**：HNSW 索引已建，适当调整 `ef_search`；全文检索考虑 GIN 索引优化。

---

### Q20：Code Chunk 和 Symbol 是怎么存的？为什么不做 GraphRAG？

**答：**

Chunk 存的是 AST 语义块（类/方法/函数），带 `relative_path`、`start_line`、`end_line`、`symbol_name`、`content`。Metadata 保存邻居信息（相邻方法/字段）。

Symbol 存的是符号定义（类名、方法签名、可见性），Relations 存的是符号间引用关系（call/import/extend/implement）。

**为什么不做完整的 GraphRAG？**
1. 我的关系图是"轻量符号引用"而不是"完整调用图"——Java 的方法重载、Spring 依赖注入、MyBatis XML 映射无法通过 Tree-sitter 可靠解析。
2. 标注了 `confidence` 和 `resolution_status` 字段，明确告诉下游"这个关系不可靠"。
3. GraphRAG 需要实体-关系建模和社区发现，对于代码审查这种任务，Token 预算更应分配给审查目标代码本身，而不是图的拓扑信息。

---

### Q21：如果让你重来一次，会做什么不同的设计？

**答：**

1. **更早建立 Benchmark**：我现在 M09 才建 Benchmark。理想情况下应该在 M06（解析完成后）就有评测骨架，这样每个模块都能用数据驱动决策。
2. **先用更简单的 Agent**：一开始就上了完整的 Planner + Reviewer + Critic 三 Agent。如果能先做一个单 Agent（直接 review + 确定性校验），验证核心链路，再逐步加 Critic，迭代会更快。
3. **Progress 更新更细粒度**：当前进度只在任务生命周期几个节点更新（5% → 15% → 100%）。图中每个节点执行后应该更新进度，用户体感更好。
4. **issue title 持久化问题**：当前有个 bug 是 issue title 有时为空，应该在 Reviewer Schema 层面加更强的校验。

---

## 八、行为面试

### Q22：这个项目中遇到的最大挑战是什么？

**答：** 最大的挑战是**让整个链路可靠地跑通**。

之前报告生成一直失败，任务 status 停留在 `failed`。问题不在于单一模块——LLM 调用正常、检索正常、Agent 正常——而是**数据在多个节点间传递时的防御性不足**。

LangGraph 的 state 经过 Planner → Reviewer → EvidenceVerify → CriticDecision → FinalizeItem 五个节点，issue dict 被反复修改和合并。任何一个节点的输出偏离预期，`_replace_issues()` 就可能因为 key 缺失而崩溃。

解决过程让我深刻理解了：**在 AI 应用中，确定性系统代码的可靠性比模型质量更重要**。模型输出不稳定是常态，系统必须能包容这种不稳定。

---

### Q23：你是怎么做技术选型的？

**答：** 选择标准：
1. **匹配需求而非追新**：pgvector 够用就不用 Milvus，FastAPI 够用就不用 Django。
2. **考虑单人维护成本**：选择 PostgreSQL 扩展而非专用向量库，减少运维负担。
3. **有明确边界**：LangGraph 只用 StateGraph + 条件边，不用它家的 Memory、Checkpoint（自己管理状态持久化）。
4. **可替换性**：LLMProvider 是 Protocol，可以随时换供应商；EmbeddingProvider 同样。Celery 和 TaskRunner 共享 `TaskDispatcher` 接口。

---

## 九、加分项

### Q24：你怎么向非技术人员解释这个项目？

**答：** 想象你写了几百个代码文件，想找人帮你检查有没有安全漏洞。但你不能把所有文件都发给一个人——太多了看不过来，而且那人可能会"脑补"一些不存在的问题。

我的系统做的事：
1. **先读代码做笔记**：把代码按功能拆成小块，给每个块打标签。
2. **找到相关部分**：当你问"检查 SQL 注入"，系统只挑出跟数据库操作相关的那些代码块。
3. **AI 做初步判断**：AI 看这些代码块，指出"这里可能有 SQL 注入"。
4. **事实核查**：系统用程序验证 AI 说的文件有没有、行号对不对、证据是否存在。AI 说"第 45 行有问题"，但文件只有 30 行？直接打回。
5. **出报告**：最终告诉你发现了几个问题、在哪里、为什么是问题、怎么修。

整个过程 AI 负责"发现可能性"，代码负责"验证事实"，两者配合。

---

### Q25：如果要写进简历，怎么写？

**答：**

> **CodeReview Agent — AI 代码审查平台**  
> Python | FastAPI | LangGraph | PostgreSQL/pgvector | Vue 3
> - 设计基于 Tree-sitter 的 Java/Python LanguageAdapter，实现 AST 语义分块和符号关系提取，新增语言不修改检索与 Agent 主流程。
> - 构建 pgvector + PostgreSQL 全文检索 + RRF 的 Hybrid RAG，通过消融实验验证相比 Keyword-only 提升 F1 从 0.333 到 0.625。
> - 基于 LangGraph 实现有界审查状态机（Planner → Retrieve → Review → EvidenceVerify → Critic），四段 BudgetGuard 控制 LLM 调用次数和 Token 预算。
> - 设计四道确定性证据校验（路径/行号/证据/Chunk 归属），拦截 LLM 幻觉，消融实验 Precision 从 0.625 提升至 1.0。
> - 实现进程内 TaskRunner 替代 Celery（Windows 兼容），SSE 实时进度 + 数据库断线恢复，单任务 21 次 LLM 调用约 2 分钟完成。

---

*文档基于真实项目 CodeReview Agent (github.com/Try-C/CodeReview)，所有技术细节、数值、Bug 修复过程均来自实际开发经历。*
