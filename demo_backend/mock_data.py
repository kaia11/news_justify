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


# MOCK_ARTICLE_BODY_2 = [
#     "刚刚，一则耸动消息在社交平台热传：Claude 新模型 Mythos 危险到让鲍威尔召集华尔街紧急开会，全美安全股暴跌 2 万亿。",
#     "热传内容声称，华尔街巨头被紧急召往华盛顿，Mythos 这个模型让美国财长和美联储主席都感到恐慌，并已向全美金融业 CEO 发出警告。",
#     "还有说法称，短短一年内，SaaS 市场已经因为这类模型冲击蒸发 2 万亿美元，并把金融恐慌、科技估值下跌和 AI 风险直接捆绑在一起。",
#     "爆料进一步指向 Anthropic，称其最新模型 Mythos 可能对金融业造成巨大风险，甚至暗示监管层已经把它视为系统性威胁。",
#     "但目前流传内容中缺少最关键的公开证据，例如会议通知、参会名单、官方声明、市场数据来源，以及 Mythos 这一模型名称本身是否真实存在。",
#     "一些说法还把 AI 安全讨论、金融市场波动和监管预警混在一起，容易让人误以为已经发生了经官方确认的紧急事件。",
#     "如果只看这些帖子，很容易得出“新模型已经引爆华尔街危机”的结论；但从信息结构看，这更像是把真实的 AI 风险讨论、宏观市场焦虑和未经证实的细节拼接成一条半真半假的爆炸性消息。",
# ]

# MOCK_NEWS_ITEMS_2 = [
#     NewsItem(
#         id="20260411-claude-mythos-wall-street-rumor",
#         news_id=2026041102,
#         title="Claude新模型危险，鲍威尔召集华尔街紧急开会！全美安全股暴跌2万亿",
#         summary="网传 Anthropic 最新模型 Mythos 危险到引发鲍威尔和美国财长紧急召集华尔街，并导致全美安全股暴跌 2 万亿。相关说法混入了真实的 AI 风险讨论和市场焦虑，但关键细节目前缺乏公开证据。",
#         url="https://example.com/mock/claude-mythos-wall-street-rumor",
#         source="社交平台热传",
#         score="9.8",
#         cover_url="",
#         raw={
#             "published_at": "2026-04-11T14:30:00+08:00",
#             "author": "Mock Desk",
#             "brief": {
#                 "headline": "Claude新模型危险，鲍威尔召集华尔街紧急开会！全美安全股暴跌2万亿",
#                 "lead": "这是一条把 AI 安全争议、金融恐慌和未经证实的高层会议细节混在一起传播的热传消息，爆点很强，但证据链明显不完整。",
#                 "paragraphs": MOCK_ARTICLE_BODY_1,
#             },
#             "content": "\n".join(MOCK_ARTICLE_BODY_1),
#         },
#     ),
# ]


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

MOCK_ARTICLE_BODY_3 = [
    "震撼！AI将取代1/3影像科医生，医学界迎来巨变。",
    "你知道吗？如今人工智能发展如此迅速，各种软件可以自动分析医学影像图片并做出诊断，比如 CT、MRI。",
    "Deepseek 预测未来十年内，医院影像科医生将面临不可逆转的变革。说实话，这个消息确实让人震惊。",
    "如果人工智能继续以当前速度发展，到 2028-2035 年，AI 系统将取代 80% 以上的常规影像判读工作。",
    "热传内容还称，CT、DR、MRI 的初筛准确率可达 99.2%，超过人类医生平均 96.8% 的准确率。",
    "按这种说法，影像科医生数量将缩减到现有规模的三分之二左右，新入职医生会直接面临 AI 竞争压力。",
    "还有说法进一步推断，影像诊断服务费会断崖式下降，单个病例收费可能降至当前价格的 15%。",
]

MOCK_NEWS_ITEMS_3 = [
    NewsItem(
        id="20250407-ai-radiology-doctors-rumor",
        news_id=2025040701,
        title="震撼！AI将取代1/3影像科医生，医学界迎来巨变",
        summary="网传随着人工智能快速发展，到 2028-2035 年，AI 将取代 80% 以上常规影像判读工作，影像科医生规模会缩减 1/3，影像诊断收费甚至可能降到现在的 15%。相关说法把技术进展、行业预测和收费变化混在一起，结论非常激进。",
        url="https://example.com/mock/ai-radiology-doctors-rumor",
        source="社交平台热传",
        score="9.1",
        cover_url="",
        raw={
            "published_at": "2025-04-07T17:00:00+08:00",
            "author": "Mock Desk",
            "brief": {
                "headline": "震撼！AI将取代1/3影像科医生，医学界迎来巨变",
                "lead": "这条消息把 AI 医学影像识别能力、未来岗位变化和医疗服务价格下降连在一起讲，听起来很惊人，但中间跨了好几层推断。",
                "paragraphs": MOCK_ARTICLE_BODY_3,
            },
            "content": "\n".join(MOCK_ARTICLE_BODY_3),
        },
    ),
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

