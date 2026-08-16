# AI 旁白 / 有声书 合规披露指南 (P2.11)

> ⚠️ **红线声明 (本仓库不替任何平台假声明其条款)**
> 各发行平台的 AI 配音标注政策随时间与地区更新。本指南只给**框架性指引与官方信息定位**,
> **不引用、不编造具体条款正文** (避免凭记忆编造过期/错误条款误导用户)。
> 各平台官方政策页面链接与具体要求, 请**由核实过的维护者按平台当前公告回填**
> (本节 `待核实` 占位即预留), 并随平台更新维护。用户分发前**务必自行核实生效地区的最新条款**,
> 本仓库不对条款时效性承担责任。

本指南覆盖 Audiobook Studio 生成的 AI 配音内容在主流发行渠道的披露/标注要点。配套:仓库的
声音克隆**样本提供者授权存证**(`tts/clone.py` VoiceSample.attestation_at/consent_version +
`api/tts_voices.py` console `consent` 422 强校验) 与 **TTS 引擎商用许可守门**
(`tts/license_guard.py` + `config/tts_licenses.yaml`),共同构成"普惠有声书"合规护栏。

---

## 1. 通用原则 (AI 生成内容披露)

无论发行至哪个平台, AI 旁白/合成的有声书通常须满足:

1. **诚实标注生成方式**: 若音频由 AI TTS 合成 (而非真人朗读), 分发描述/元数据中应明确标注
   "AI 旁白" / "AI 配音" / "Synthesized speech", 不得伪装为真人朗读。
2. **样本来源授权**: 克隆任何真人声音须获声音本人**明确授权** (本仓库在克隆前强制 consent 勾选 +
   存证)。使用预设音色 (非克隆) 不涉及个人授权, 但仍受引擎 license 约束 (见 §4)。
3. **版权内容许可**: 合成文本须有合法授权 (公有领域 / 自有版权 / 已获授权), 仓库不替文本版权背书。
4. **地区与平台差异**: 各国对 AI 生成内容的规定不同 (如欧盟 AI Act 标注义务、美国 FTC 透明度
   要求、中国《生成式人工智能服务管理暂行办法》标识义务); 发行地为准据法前须自行核实。

---

## 2. Audible / ACX (Amazon)

- **性质**: ACX 是 Audible 的有声书制作分发平台。近年已发布针对 AI 叙述 (AI-narrated) 内容的
  标注政策。
- **披露要点 (框架)**: 制作人在 ACX 上传 AI 合成有声书时, 须按平台选项如实标注使用 AI, 并声明
  AI 使用的阶段 (如旁白生成 / 母带制作)。平台对 "AI-narrated" 与 "AI-voiced / voice-cloned"
  通常有区分标注。
- **待核实 (用户/维护者回填)**:
  - ACX 当前 AI 叙述内容政策页官方链接: `待核实 — 请回填 ACX 官方公告页 URL`
  - Audible 对听众展示 AI 标注的具体展示形式与字段要求: `待核实`
  - 声音克隆在 ACX 的额外授权要求 (是否需声音本人书面许可存档): `待核实`
- ⚠️ 本仓库**不确定**上述政策的当前条款文本; 务必前往 ACX 官方帮助中心核实。

## 3. Findaway Voices / Spotify audiobooks

- **性质**: Findaway 是有声书分发聚合商, 已并入 Spotify 体系。
- **披露要点 (框架)**: Findaway 等聚合平台对 AI 生成有声书的接受度与标注字段随其政策更新。
  AI 合成内容常需在元数据中选 "AI-narrated" 或在描述中声明。
- **待核实 (用户/维护者回填)**:
  - Findaway 当前 AI 旁白政策与提交要求官方链接: `待核实 — 请回填官方政策页 URL`
  - Spotify 对 AI 叙述有声书的展示与披露要求: `待核实`
- ⚠️ 请前往 Findaway / Spotify 官方页面核实当前政策。

## 4. 喜马拉雅 (Ximalaya) 及国内平台

- **性质**: 中国境内主流有声内容平台。受《生成式人工智能服务管理暂行办法》《互联网信息服务深度
  合成管理规定》等约束, AI 生成/深度合成内容通常须**显著标识**其 AI 生成属性。
- **披露要点 (框架)**:
  - 深度合成 (含 AI 声音克隆、声音生成) 内容须显著标识 "AI 生成" / "由 AI 生成"。
  - 利用他人声音克隆须获本人同意 (与本仓库克隆前 consent 存证一致)。
  - 平台上架时如有 "AI 生成" 标签字段须如实勾选, 不得隐瞒。
- **待核实 (用户/维护者回填)**:
  - 喜马拉雅深度合成/AI 内容标注规则官方链接: `待核实 — 请回填官方公告/规则页 URL`
  - 喜马拉雅声音克隆与 AI 配音的上架资质/备案要求: `待核实`
  - 其他国内发行平台 (如蜻蜓、番茄畅听等) 的 AI 标注要求: `待核实`
- ⚠️ 各地网信办与平台的标识细则更新较快, 分发前请核实生效中规则并据以标注。

---

## 5. TTS 引擎商用许可 (与 license_guard 联动)

引擎 license 决定合成音频能否商用分发 (`pro_studio` 等商用档受
`tts/license_guard.py` 守门):

| 引擎 | commercial_use (来自 `config/tts_licenses.yaml`) | 说明 |
|---|---|---|
| kokoro | `null` (待核实) | Kokoro-82M 权重 license 待核实官方 model card 后维护者回填 |
| edge | `null` (待核实) | 微软 Edge TTS 的商用可用性未由微软明文授权, 需核实 TOS |
| voxcpm2 | `null` (待核实) | OpenBMB/VoxCPM2 官方许可待核实 |
| cosyvoice | `null` (待核实) | FunAudioLLM/CosyVoice 官方许可待核实 |

**红线**: 仓库当前对全部引擎标 `null` (未核实) —— 这**不等于**商用授权。商用分发前,
**维护者须凭已核实的官方 license 文本**在 `config/tts_licenses.yaml` 填 `commercial_use`
(`true`/`false`) + `license_name` + `verified_at`。守门逻辑:

- 非商用档 (potato): 全引擎放行 (本是个人/离线场景)。
- 商用档 (`pro_studio` / `cloud_hybrid` 等): `commercial_use=false` → 阻断注册 (诚实噪止,
  不假装就绪); `null` → 降级 `warn_unverified` (未核实, 不假成功也不误杀, 凭核实后转阻断或放行)。

---

## 6. 合规自检清单 (分发前)

- [ ] 合成音频已在发行平台如实标注 "AI 旁白/AI 合成"。
- [ ] 克隆声音已获本人授权 (本仓库 VoiceSample 存证 `attestation_at` + `consent_version`)。
- [ ] 合成文本版权已获合法授权或有公有领域依据。
- [ ] 所用 TTS 引擎已核实其 license 支持目标分发场景 (回填 `config/tts_licenses.yaml`)。
- [ ] 已核实发行地区 AI 生成内容的最新法定标识要求并据以标注。

---

## 维护说明

本指南为框架性合规指引, 不替任何平台/法律给出条款正文。平台政策更新时请:

1. 由核实过官方当前公告的维护者回填各 `待核实` 字段 (官方链接 + 摘要要点)。
2. 在本文件顶部注明策略核实日期。
3. 同步更新 `config/tts_licenses.yaml` 的引擎 license (若平台政策影响商用判定)。

相关代码:`src/audiobook_studio/tts/license_guard.py` · `config/tts_licenses.yaml` ·
`tts/clone.py` (VoiceSample attestation) · `api/tts_voices.py` (consent 422 强校验)。
