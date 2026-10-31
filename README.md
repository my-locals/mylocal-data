# mylocal-data

[MyLocal](https://mylocal.myiam.io)이 서버 버전의 지원 상태를 보여 줄 때 쓰는 자료입니다. 앱은 이 파일 전체를 받아 Mac 안에서만 비교하므로, 어떤 프로그램을 쓰는지는 여기로 전해지지 않습니다.

- **자료:** [`data/support.json`](data/support.json). [endoflife.date](https://endoflife.date)(MIT, [`NOTICE`](NOTICE))에서 만든 제품별 릴리스 라인, 지원 종료일, 최신 패치입니다. 제품 하나가 한 줄이라 `git log -p`로 무엇이 바뀌었는지 읽을 수 있습니다.
- **받는 곳:** `releases/latest/download/support.json`과 `support.json.minisig`.
- **서명:** minisign 형식입니다. 공개 키는 [`public-key.txt`](public-key.txt)이고 앱에 들어 있습니다. 비밀 키는 Actions 비밀값 `SIGNING_KEY`에만 있고, 앱 업데이트 키와 다릅니다.

## 받은 파일이 하는 일

표시만 합니다. 앱은 이 자료로 어떤 서버도 멈추거나 살려 두지 않고, 자료 안의 어떤 값도 실행하지 않습니다. 잘못된 자료로 일어날 수 있는 일은 틀린 지원 상태 표시이고, 아래 검사는 그것을 막기 위한 것입니다.

- **게시 전 (`build.py`):** 형식을 검사하고, 지난 자료와 비교해 하루치로 보기 어려운 변화(제품·릴리스 라인 5% 초과 삭제, 지원 종료일 25건 초과 연장, 최신 버전 10건 초과 하락, 종료된 라인 10건 초과 부활)가 있으면 게시하지 않습니다. 워크플로가 실패하고 지난 자료가 그대로 남습니다.
- **앱에서:** 서명, 크기, 형식을 확인하고, 가지고 있는 자료보다 오래된 파일은 거부합니다. 실패하면 받아 둔 자료나 앱에 들어 있는 자료를 씁니다.

## 게시

`.github/workflows/publish.yml`이 매일 실행합니다. 외부 액션은 커밋으로 고정한 `actions/checkout`뿐이고, 비밀 키는 서명 단계에만, 쓰기 토큰은 게시 단계에만 들어갑니다.

변화가 많아 멈췄다면 `git diff`로 내용을 확인한 뒤, 정상이면 Actions에서 `force`를 켜고 다시 실행합니다.

```bash
./test_build.py    # 네트워크 없이 검사
./build.py         # 받아서 검사하고 data/support.json을 씀
```

## 키를 바꿀 때

앱에 공개 키가 들어 있으므로 앱 업데이트가 함께 필요합니다. 그때까지 옛 앱은 새 파일을 거부하고 받아 둔 자료를 계속 씁니다.

1. `./sign.py --new-key 2>public-key.txt | gh secret set SIGNING_KEY`
2. MyLocal의 `crates/mylocal-platform/src/support_data.rs`에서 `PUBLIC_KEY`를 바꾸고 앱을 릴리스합니다.
