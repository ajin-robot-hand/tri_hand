# 시연 명령어 메모

2분 구동 시험(`default` ↔ `상자` 쥐기 순환)을 시연할 때 쓰는 명령어입니다. 순서대로 실행하세요.

## 1. 가상환경 진입 (Windows PowerShell)

```powershell
..\mujoco_env\Scripts\Activate.ps1
```

`(mujoco_env)`가 명령줄 앞에 붙으면 성공입니다. (CMD는 `..\mujoco_env\Scripts\activate.bat`, Git Bash는 `source ../mujoco_env/Scripts/activate`)

## 2. 서버 실행 (0번 창)

```powershell
python real/server.py --log logs
```

`CSV 로깅: logs/<날짜시각>`이 출력되는지 확인합니다.

## 3. 2분 구동 러너 실행 (1번 창)

```powershell
python real/endurance.py --grips 상자 --minutes 2
```

- `상자` 프리셋으로 30초 쥐기 → `default`(홈 자세)로 90초 펴기, 한 사이클(2분) 실행.
- 끝나면 자동으로 `default` 복귀 + 토크 off.
- 종료 시 요약(구동 시간·통신 실패 횟수·최고 온도·패킷 에러율·지터·가용률)이 출력됩니다.

## 참고

- 물체 없이 쥐면 모터 부하가 거의 걸리지 않아 온도는 크게 오르지 않습니다. 이 시험은 동작 순서·통신·50 Hz 루프 확인용입니다.
- 그립 종류를 바꾸려면 `--grips` 뒤에 다른 프리셋 이름(`물병`, `휴지심`)을 넣으면 됩니다.
- 자세한 배경은 [today_to_do.md](today_to_do.md) 참고.
