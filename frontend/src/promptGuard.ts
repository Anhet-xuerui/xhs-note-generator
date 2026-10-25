/**
 * 契约提醒（D10-7）：默认 prompt 里有几句是**代码强校验**的。
 * 删掉不拦你保存，但要让黄色提示先说清楚代价。
 */

interface ContractRule {
  keyword: string
  hint: string
}

const RULES: Record<string, ContractRule[]> = {
  planner: [
    { keyword: 'chosen', hint: '代码要求三个角度里恰好一个 chosen=true，删掉这句会被反复重问。' },
    { keyword: 'why_not_others', hint: '代码要求每个角度都写 why_not_others，缺一条直接判违约。' },
  ],
  writer: [
    { keyword: 'objection_index', hint: '代码要求 objection_index 完整覆盖上一轮意见，否则重出一次。' },
    { keyword: 'real_material', hint: '主笔至少要引用两条 real_material，否则会带着提示重写一次。' },
  ],
  gatekeeper: [
    { keyword: 'findings', hint: '守门人输出必须是 findings 列表，且与正则命中一一对应。' },
  ],
}

export function contractWarnings(role: string, text: string): string[] {
  const warnings: string[] = []
  if (!text.includes('JSON')) {
    warnings.push('默认要求「只输出 JSON」：删掉这句，模型很可能回一段散文，直接被丢弃重问。')
  }
  for (const rule of RULES[role] ?? []) {
    if (!text.includes(rule.keyword)) warnings.push(rule.hint)
  }
  return warnings
}
