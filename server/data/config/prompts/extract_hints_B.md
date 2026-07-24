- product(可报名产品)的规范名只有六个(第二章产品表):**L1暑期集训班、L1周末研修班、
  L2暑期集训班、L2周末研修班、L3暑期集训班、L3周末研修班**。
  第一章的等级定义、第三章的等级与认证产出、第五章的价格与费用包含,都必须作为 attrs
  挂到这六个规范名实体上(level/fee/includes/prereq_text),不得新建产品实体。
- format:暑期集训班为 offline;**周末研修班为 hybrid**(线上+线下工作坊混合),不要标成 offline。
- 「L1:AI教学工具应用」「L2:AI教学应用开发」「L3:AI教育项目交付」是**等级定义**,
  抽取为 type=other,attrs 含 level/hours/target/output,不要作为 product。
- 每个产品实体应含 start/end/deadline(报名截止)/hours/venue。
