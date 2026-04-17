from demo_backend.models import IssueItem, IssuePayload, NewsItem

MOCK_ARTICLE_BODY_1 = [
    "刚刚，一则耸动消息在社交平台热传：Claude 新模型 Mythos 危险到让鲍威尔召集华尔街紧急开会，全美安全股暴跌 2 万亿。",
    "热传内容声称，华尔街巨头被紧急召往华盛顿，Mythos 这个模型让美国财长和美联储主席都感到恐慌，并已向全美金融业 CEO 发出警告。",
    "还有说法称，短短一年内，SaaS 市场已经因为这类模型冲击蒸发 2 万亿美元，并把金融恐慌、科技估值下跌和 AI 风险直接捆绑在一起。",
    "爆料进一步指向 Anthropic，称其最新模型 Mythos 可能对金融业造成巨大风险，甚至暗示监管层已经把它视为系统性威胁。",
    "但目前流传内容中缺少最关键的公开证据，例如会议通知、参会名单、官方声明、市场数据来源，以及 Mythos 这一模型名称本身是否真实存在。",
    "一些说法还把 AI 安全讨论、金融市场波动和监管预警混在一起，容易让人误以为已经发生了经官方确认的紧急事件。",
    "如果只看这些帖子，很容易得出“新模型已经引爆华尔街危机”的结论；但从信息结构看，这更像是把真实的 AI 风险讨论、宏观市场焦虑和未经证实的细节拼接成一条半真半假的爆炸性消息。",
]

MOCK_NEWS_ITEMS_1 = [
    NewsItem(
        id="20260411-claude-mythos-wall-street-rumor",
        news_id=2026041102,
        title="Claude新模型危险，鲍威尔召集华尔街紧急开会！全美安全股暴跌2万亿",
        summary="网传 Anthropic 最新模型 Mythos 危险到引发鲍威尔和美国财长紧急召集华尔街，并导致全美安全股暴跌 2 万亿。相关说法混入了真实的 AI 风险讨论和市场焦虑，但关键细节目前缺乏公开证据。",
        url="https://example.com/mock/claude-mythos-wall-street-rumor",
        source="社交平台热传",
        score="9.8",
        cover_url="",
        raw={
            "published_at": "2026-04-11T14:30:00+08:00",
            "author": "Mock Desk",
            "brief": {
                "headline": "Claude新模型危险，鲍威尔召集华尔街紧急开会！全美安全股暴跌2万亿",
                "lead": "这是一条把 AI 安全争议、金融恐慌和未经证实的高层会议细节混在一起传播的热传消息，爆点很强，但证据链明显不完整。",
                "paragraphs": MOCK_ARTICLE_BODY_1,
            },
            "content": "\n".join(MOCK_ARTICLE_BODY_1),
        },
    ),
]


MOCK_ARTICLE_BODY_2 = [
    "OpenAI惨遭反超！Anthropic狂吞70%新客户，Claude已开启灵魂校准",
    "编辑：犀牛",
    "【新智元导读】当企业真金白银开始从 ChatGPT 流向 Claude，Anthropic 打的早已不只是模型性能战，而是一场从工程师口碑、企业信任到「AI灵魂校准」的全面突围。",
    "这一次，Anthropic真的要把OpenAI从「企业AI王座」上拽下来了。",
    "美国企业财务卡发行商 Ramp 最新发布的 AI Index 数据，几乎是把一颗炸弹扔进了硅谷——在它追踪的5万多家美国企业中，已经有一半在为AI产品付费。",
    "其中，使用Anthropic的客户占比已经飙升到 30.6%，单月暴涨 6.3 个百分点；而OpenAI呢？掉到了 35.2%。",
    "差距，从今年2月的整整 11 个百分点，一个月内被砍到 4.6 个点。",
]

MOCK_NEWS_ITEMS_2 = [
    NewsItem(
        id="20260413-openai-anthropic-claude-ramp",
        news_id=2026041301,
        title="OpenAI惨遭反超！Anthropic狂吞70%新客户，Claude已开启灵魂校准",
        summary="Ramp最新AI Index数据显示，在美国5万多家企业中，Anthropic客户占比一个月内暴涨至30.6%，OpenAI跌至35.2%，差距从11个百分点急剧缩小到4.6个百分点。Anthropic正通过工程师口碑、企业信任和「AI灵魂校准」全面冲击OpenAI的企业AI王座。",
        url="https://aiera.com.cn/2026/04/13/other/aiera-com-cn/89701/openai%e6%83%a8%e9%81%ad%e5%8f%8d%e8%b6%85%ef%bc%81anthropic%e7%8b%82%e5%90%9e70%e6%96%b0%e5%ae%a2%e6%88%b7%ef%bc%8cclaude%e5%b7%b2%e5%bc%80%e5%90%af%e7%81%b5%e9%ad%82%e6%a0%a1%e5%87%86/",
        source="新智元",
        score="8.5",
        cover_url="",
        raw={
            "published_at": "2026-04-13T08:30:00+08:00",
            "author": "新智元 / 犀牛",
            "brief": {
                "headline": "OpenAI惨遭反超！Anthropic狂吞70%新客户，Claude已开启灵魂校准",
                "lead": "当企业真金白银开始从 ChatGPT 流向 Claude，Anthropic 打的早已不只是模型性能战，而是一场从工程师口碑、企业信任到「AI灵魂校准」的全面突围。",
                "paragraphs": MOCK_ARTICLE_BODY_2,
            },
            "content": "\n".join(MOCK_ARTICLE_BODY_2),
        },
    ),
]


MOCK_ARTICLE_BODY_4 = [
    "2026 年 4 月 4 日，Anthropic 宣布 Claude 订阅服务不再覆盖 OpenClaw 等第三方工具的使用额度，后续使用需额外购买用量包或绑定 API Key 按量付费。",
    "该政策先对 OpenClaw 执行，随后将逐步推广至更多第三方工具链，直接改变了不少团队原有的低固定成本使用方式。",
    "帖子称 OpenClaw 创始人 Peter Steinberger 与董事会成员曾争取缓冲期，最终仅获得 7 天宽限，未能改变封锁结果。",
    "官方解释主要包括两点：第三方高频调用超出订阅模型初始设计边界，以及在 GPU 紧张背景下需要优先保障 Claude 自有产品和 API 用户体验。",
    "文中还梳理了此前的围堵轨迹，包括命名争议、功能替代和生态收口，认为这次动作是平台策略收紧的延续而非单点事件。",
    "文章进一步提出，OpenClaw 的高算力利用效率在固定订阅下可能造成平台侧成本失衡，这是商业层面推动规则收紧的重要原因。",
    "结论是 AI 行业正在从开放红利阶段转入平台主权阶段，第三方工具若过度依赖单一平台，面临的政策与成本风险会显著上升。",
]

MOCK_NEWS_ITEMS_4 = [
    NewsItem(
        id="20260404-deepseek-topic-1356-openclaw",
        news_id=2026040404,
        title="突发！Claude 全面封杀 OpenClaw，创始人哭求仅换 7 天续命，AI 开放红利正式退潮",
        summary="深求社区 topic/1356 报道 Anthropic 收紧第三方工具调用策略：Claude 订阅不再覆盖 OpenClaw 等工具额度，开发者成本结构与生态关系受到明显冲击。",
        url="https://discuss.deepseek.club/t/topic/1356",
        source="深求社区（DeepSeek.club）",
        score="9.0",
        cover_url="https://discuss.deepseek.club/uploads/default/optimized/2X/7/716bcfc6bb9178dd0e634ef7516d3ead15aeb927_2_868x1024.jpeg",
        raw={
            "published_at": "2026-04-04T14:24:13Z",
            "author": "MondayOptimist",
            "brief": {
                "headline": "突发！Claude 全面封杀 OpenClaw，创始人哭求仅换 7 天续命，AI 开放红利正式退潮",
                "lead": "帖子聚焦 Anthropic 对 OpenClaw 的策略收紧及其对开发者成本、第三方生态和平台关系的影响。",
                "paragraphs": MOCK_ARTICLE_BODY_4,
            },
            "content": "\n".join(MOCK_ARTICLE_BODY_4),
        },
    )
]


MOCK_ARTICLE_BODY_3 = [
    "2026 年 4 月，AI 圈被一则关于 GPT-6 的爆料引爆：帖文称该模型代号“Spud”，已完成预训练和安全测试，可能在 4 月中旬发布。",
    "文中称 GPT-6 在代码生成、逻辑推理和智能体任务上相较 GPT-5.4 提升约 40%，并支持 200 万 Token 超大上下文窗口。",
    "帖子同时提到形态层面的整合方向：ChatGPT、Codex 与 Atlas 浏览器能力将进一步融合，向“桌面级超级应用”推进。",
    "价格方面，爆料给出每百万 Token 输入约 2.5 美元、输出约 12 美元的预期，强调高性能与平价并行的策略。",
    "战略层面，文章讨论了 OpenAI 收缩 Sora、聚焦 AGI 的取舍逻辑，认为核心约束来自算力与资源分配效率。",
    "除 GPT-6 外，文中还提到 GPT-Image 2 的阶段性亮相，认为其在复杂界面复刻和高保真生图上表现突出。",
    "全文结论是：AI 竞争已进入深水区，GPT-6 若如期落地将是 2026 年关键变量，但具体发布时间与能力仍需官方确认。",
]

MOCK_NEWS_ITEMS_3 = [
    NewsItem(
        id="20260405-deepseek-topic-1372-gpt6-rumor",
        news_id=2026040503,
        title="GPT-6 爆料疯传！4 月 14 日发布？OpenAI 砍 Sora 押注 AGI，GPT-Image 2 生图以假乱真",
        summary="来源于深求社区 topic/1372 的新闻帖，围绕 GPT-6 爆料、Sora 资源收缩与 GPT-Image 2 进展展开，具体细节仍需官方后续确认。",
        url="https://discuss.deepseek.club/t/topic/1372",
        source="深求社区（DeepSeek.club）",
        score="8.9",
        cover_url="https://discuss.deepseek.club/uploads/default/optimized/2X/9/985b5f3b97bb9bbad43802f2e281fe7ba2359f87_2_1024x427.png",
        raw={
            "published_at": "2026-04-05T12:09:43Z",
            "author": "xigua",
            "brief": {
                "headline": "GPT-6 爆料疯传！4 月 14 日发布？OpenAI 砍 Sora 押注 AGI，GPT-Image 2 生图以假乱真",
                "lead": "帖子聚焦 GPT-6 发布传闻与能力升级，同时延展到 OpenAI 战略收缩和多模态产品演进。",
                "paragraphs": MOCK_ARTICLE_BODY_3,
            },
            "content": "\n".join(MOCK_ARTICLE_BODY_3),
        },
    )
]


MOCK_ARTICLE_BODY_5 = [
    "帖子以 MEDVi 为案例，提出 AI 创业可通过“极小核心团队 + AI 全栈前台 + 第三方外包后端”实现高效率增长。",
    "文中称 MEDVi 在 2024 年下半年成立，核心团队一度仅 2 人，主营远程减重医疗服务，并给出 2025 年营收约 4.01 亿美元、2026 年预计约 18 亿美元的增长叙事。",
    "其结构要点是：前端营销、客服、筛选与运营由 AI 自动化处理，医生、处方、药房、物流等重资产环节交由外部专业机构履约。",
    "帖子强调 AI 在获客投放、7x24 客服、用户分层运营和内容生产方面显著压缩人力成本，使小团队可承接高流量业务。",
    "文章同时提示该模式存在合规边界，尤其在医疗场景下，营销内容与流程仍受监管约束，AI 不能替代法律与合规责任。",
    "除 MEDVi 外，文中还列举了多家“AI 前台 + 外包后端”案例，认为这一组合正在成为轻量化创业的可复制范式。",
    "结论是公司规模与增长越来越取决于自动化程度、流程重构与外包生态协同，而非传统的人数和重资产扩张。",
]

MOCK_NEWS_ITEMS_5 = [
    NewsItem(
        id="20260413-deepseek-topic-1512-medvi",
        news_id=2026041312,
        title="2 人干出 18 亿美元营收：MEDVi 揭秘 AI 轻量化创业的极致范式",
        summary="深求社区 topic/1512 以 MEDVi 为样本，讨论“AI 前台自动化 + 后端专业外包”的轻量化创业路径，强调高增长潜力与合规边界并存。",
        url="https://discuss.deepseek.club/t/topic/1512",
        source="深求社区（DeepSeek.club）",
        score="8.8",
        cover_url="https://discuss.deepseek.club/uploads/default/original/1X/6273b6258641ff27b15ee0a9585d524d0d774de5.png",
        raw={
            "published_at": "2026-04-13T06:49:44Z",
            "author": "earnest",
            "brief": {
                "headline": "2 人干出 18 亿美元营收：MEDVi 揭秘 AI 轻量化创业的极致范式",
                "lead": "该帖聚焦 AI 轻量化创业的组织范式，主张把可标准化前端流程交给 AI，把重资产后端交给成熟外部生态。",
                "paragraphs": MOCK_ARTICLE_BODY_5,
            },
            "content": "\n".join(MOCK_ARTICLE_BODY_5),
        },
    )
]




def build_mock_issue() -> IssuePayload:
    items = [
        IssueItem(
            id=item.id,
            news_id=item.news_id,
            source=item.source,
            headline=item.title,
            warning=item.summary,
            article_url=item.url,
            cover_image=item.cover_url,
            expanded_body=item.raw.get("brief", {}).get("paragraphs", [item.summary]),
        )
        for item in MOCK_NEWS_ITEMS_3
    ]

    return IssuePayload(
        id="mock-latest",
        title="示例新闻速览 / 本地调试",
        subtitle="当前使用 Claude / Mythos 引发华尔街恐慌的热传消息作为 mock 新闻，方便测试核查、写作和漫画生成效果。",
        footer="当 mock=false 时，后端会改为从云端榜单拉取最新新闻。",
        source_mode="mock",
        items=items,
    )


