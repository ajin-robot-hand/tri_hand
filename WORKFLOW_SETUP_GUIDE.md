# 프로젝트 자동화 및 깃허브 워크플로우 이식 가이드

이 문서는 `tri_hand` 프로젝트에 구축된 **[README 템플릿 + GitHub PR 템플릿 + Git PR 원스톱 자동화 스킬]** 환경을 다른 신규 또는 기존 프로젝트에 그대로 복사하여 30초 만에 적용하는 가이드입니다.

---

## 1. 핵심 에셋 구성 요소

| 구분 | 파일/폴더 경로 | 역할 |
| :--- | :--- | :--- |
| **README 템플릿** | [`README_TEMPLATE.md`](README_TEMPLATE.md) | 엔지니어링 모범 사례와 시각화·OS별 퀵스타트가 포함된 프로젝트 리드미 템플릿 |
| **GitHub PR 템플릿** | [`.github/pull_request_template.md`](.github/pull_request_template.md) | 깃허브 PR 생성 시 `Summary - Key Changes - Result - Checklist` 구조를 자동 호출 |
| **원샷 PR 스킬** | [`.agents/skills/git-pr/SKILL.md`](.agents/skills/git-pr/SKILL.md) | "PR 올려줘" 한 마디로 브랜치 생성부터 커밋·푸시·PR 작성을 끝내는 Antigravity 스킬 |
| **에이전트 규칙** | [`AGENTS.md`](AGENTS.md) | 에이전트가 Git 작업 시 추가 질문 없이 원스톱 실행하도록 규정한 행동 지침 |

---

## 2. 새 프로젝트에 한 번에 복사하기

터미널에서 대상 프로젝트 경로(`TARGET_DIR`)를 지정한 후 복사 명령을 실행합니다:

```bash
# 1) 대상 프로젝트 경로 설정 (원하는 경로로 수정)
TARGET_DIR="/path/to/new-project"

# 2) 필수 폴더 및 템플릿 일괄 복사
mkdir -p "$TARGET_DIR/.github" "$TARGET_DIR/.agents/skills/git-pr"
cp -r .github/pull_request_template.md "$TARGET_DIR/.github/"
cp -r .agents/skills/git-pr/SKILL.md   "$TARGET_DIR/.agents/skills/git-pr/"
cp README_TEMPLATE.md                 "$TARGET_DIR/README.md"
```

> 💡 **참고**: 만약 대상 프로젝트에 이미 `AGENTS.md`나 `GEMINI.md`가 있다면, [AGENTS.md](AGENTS.md)의 **`## 6. Git & PR 워크플로우 규칙`** 섹션 내용만 복사하여 붙여넣으시면 됩니다.

---

## 3. (추천) 내 PC의 모든 프로젝트에 영구 적용하는 방법 (글로벌 스킬)

프로젝트마다 `.agents/` 폴더를 매번 복사하지 않고, **내 컴퓨터의 모든 프로젝트**에서 "PR 올려줘" 기능을 상시 사용하고 싶다면 홈 디렉토리의 글로벌 스킬 폴더에 등록하세요:

```bash
# 글로벌 스킬 디렉토리 생성 및 스킬 복사
mkdir -p ~/.gemini/config/skills/git-pr
cp .agents/skills/git-pr/SKILL.md ~/.gemini/config/skills/git-pr/
```

* 이렇게 설정해 두면 어떤 디렉토리에서 Antigravity를 열어도 별도의 설정 없이 `git-pr` 스킬이 항상 활성화됩니다.

---

## 4. 실제 작업 워크플로우

1. **작업 진행**: 평소처럼 자유롭게 코드를 수정하거나 문서를 작성합니다.
2. **한 마디 요청**: 작업이 끝나면 채팅창에 다음과 같이 요청합니다:
   > *"지금까지 수정한 내용 PR 올려줘"*
3. **원스톱 자동 실행**:
   - [x] 변경사항(`git status`, `git diff`) 자동 분석
   - [x] 변경 성격에 맞는 영문 브랜치 자동 생성 (`git checkout -b <type>/<description>`)
   - [x] Conventional Commits 규칙의 한국어 커밋 (`git commit -m "<type>(<scope>): <한국어 요약>"`)
   - [x] 원격 저장소 푸시 (`git push -u origin <branch>`)
   - [x] 템플릿(Summary, Key Changes, Result, Checklist)이 완벽히 채워진 GitHub PR 자동 생성 및 원클릭 링크 제공

---

## 5. 커스터마이징 팁

* **PR 체크리스트 수정**: `.github/pull_request_template.md` 파일에서 프로젝트 특성에 맞추어 테스트 항목, 빌드 점검 항목 등을 추가하거나 수정하세요.
* **커밋 규칙 변경**: `.agents/skills/git-pr/SKILL.md`에서 기본 커밋 언어(한국어/영어)나 스코프 명명 규칙을 자유롭게 튜닝할 수 있습니다.
