---
name: git-pr
description: >-
  Use this skill whenever the user asks to create a pull request (PR), push work,
  or commit and submit changes (e.g., "PR 올려줘", "작업 내용 푸시하고 PR 생성해줘", "깃 정리해서 올려줘").
  Automates the complete workflow: creating an English kebab-case branch, committing with Korean
  conventional commit message, pushing to origin, and creating a structured GitHub PR.
---

# Git & GitHub PR 자동화 워크플로우 (One-Shot Git PR Workflow)

이 스킬은 코드 수정이 완료된 후 사용자가 **"PR 올려줘"** 한 마디만 요청해도 브랜치 생성부터 커밋, 푸시, PR 본문 작성까지 모든 과정을 한 번에 처리하기 위한 지침입니다.

---

## 자동 실행 단계 (Automated Steps)

사용자가 PR 생성 또는 푸시를 요청하면 아래 5단계를 **사용자에게 추가 질문 없이 연속으로 실행**합니다.

### 1단계: 변경사항 분석 (Inspect Changes)
1. `git status` 및 `git diff`를 실행하여 수정/추가/삭제된 파일과 변경 핵심을 파악합니다.
2. 현재 브랜치를 확인합니다 (`git branch --show-current`).
   - 만약 이미 작업 브랜치에 있고 커밋되지 않은 상태라면 해당 브랜치를 유지하거나 필요 시 새 브랜치를 생성합니다.
   - `main` 브랜치에 있다면 반드시 2단계의 새 브랜치를 생성합니다.

### 2단계: 영문 특징 브랜치 생성 (Create English Branch)
수정 내용의 성격과 도메인을 반영한 영문 `kebab-case` 브랜치명을 자동 결정하고 체크아웃합니다:
* **규칙**: `<type>/<short-english-description>`
  - 기능 추가: `feat/setup-mujoco-env`, `feat/teleop-webcam-pipeline`
  - 버그 수정: `fix/joint-torque-limit`, `fix/packet-timeout-retry`
  - 문서 작업: `docs/readme-template-guide`, `docs/hardware-wiring`
  - 리팩토링: `refactor/server-modularization`
* **명령어**:
  ```bash
  git checkout -b <type>/<description>
  ```

### 3단계: 한국어 컨벤션 커밋 (Conventional Commit)
모든 변경사항을 스테이징하고, 지정된 컨벤션에 맞추어 **한국어 커밋 메시지**로 커밋합니다:
* **규칙**: `<type>(<scope>): <한국어 간결한 요약>`
  - 예: `feat(simulation): mujoco 환경 세팅 및 hand 모델 추가`
  - 예: `fix(real): 다이나믹셀 통신 재시도 로직 보완`
  - 예: `docs(readme): 프로젝트 범용 템플릿 및 가이드 추가`
* **명령어**:
  ```bash
  git add .
  git commit -m "<type>(<scope>): <한국어 요약>"
  ```

### 4단계: 원격 저장소 푸시 (Push to Origin)
생성한 브랜치를 원격 저장소(origin)로 푸시합니다:
```bash
git push -u origin <branch-name>
```

### 5단계: 깃허브 PR 생성 및 안내 (Create Pull Request)
1. **PR 타이틀 (영문)**:
   - `<type>(<scope>): <English imperative title>`
   - 예: `feat(simulation): add MuJoCo simulation environment setup`
   - 예: `docs(readme): provide universal README template and guide`

2. **PR 본문 (Repository Template 규격 준수)**:
   `.github/pull_request_template.md`의 구조를 따라 상세 내용을 작성합니다:
   ```markdown
   ## 1. Summary (개요)
   - 변경 목적 및 배경 설명 (1~2문장)

   ## 2. Key Changes (주요 변경 사항)
   - 구체적인 수정 모듈 및 기능 설명 (불릿 포인트)

   ## 3. Result / Verification (검증 결과)
   - 단위 테스트 통과 결과 또는 로컬 구동 검증 내용

   ## 4. Checklist (체크리스트)
   - [x] 브랜치 네이밍 규칙 준수 (영문 kebab-case)
   - [x] 커밋 메시지 컨벤션 준수 (한국어)
   - [x] 불필요한 디버그 코드 및 임시 파일 삭제 여부 확인
   - [x] 관련 기술 문서 업데이트 여부
   ```

3. **PR 등록 처리**:
   - `which gh`로 GitHub CLI가 설치되어 있고 인증되어 있다면:
     ```bash
     gh pr create --title "<PR_TITLE>" --body "<PR_BODY>"
     ```
   - `gh` CLI가 없거나 인증되지 않은 경우:
     - 원격 저장소 URL(예: `https://github.com/<owner>/<repo>/compare/main...<branch>?expand=1`)로 원클릭 생성 링크를 생성하여 제공하고, 복사해서 쓸 수 있는 PR 제목과 본문을 완성된 마크다운 코드블록으로 함께 출력합니다.
