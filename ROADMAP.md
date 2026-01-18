# SDNA Development Roadmap

## Current Phase: DUO + Sophia

### 1. DUOAgent Class (SDNA) ✅ DONE
- [x] Build DUOAgent class in `/tmp/sdna-repo/sdna/duo.py`
- [x] SDNAC (target) + OVPChain (evaluator) in refinement loop
- [x] to_graph() for LangGraph integration
- [x] v0.3.0 published

### 2. Sophia-MCP ✅ DONE
- [x] Build sophia-mcp with FastMCP at /tmp/sophia-mcp
- [x] ask_sophia(context) - routing/analysis, complexity level, resume_id
- [x] construct(prompt, resume_id) - chain design (quarantined)
- [x] golden_management(operation, query_or_name) - Sanctus goldenization

### 3. CAVE Discord Automations
- [ ] CogLog -> Discord webhook
- [ ] DeliverableLog -> Discord channel
- [ ] SkillLog -> Discord notifications

### 4. SancRev PAIAB Testing
- [ ] Return to sanctuary-revolution
- [ ] PAIAB testing with Discord broadcast
- [ ] Journey broadcasting to Discord

### 5. Content Pipeline
- [ ] Blog system setup
- [ ] Socials automation
- [ ] ATIA content generation from DeliverableLog

---

## Reference Docs
- DUO Framework: `/tmp/sdna-repo/duo/duo.md`
- Sophia Architecture: `/tmp/sdna-repo/duo/SOPHIA_ARCHITECTURE.md`
- SDNA Skill: `/tmp/heaven_data/skills/understand-sdna/SKILL.md`
