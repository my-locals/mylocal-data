# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 이 저장소

MyLocal Mac 앱이 서버 버전의 지원 여부와 알려진 보안 공지를 보여 줄 때 내려받는 자료입니다. `build.py`가 `data/support.json`을, `advisories.py`가 `data/advisories.json`을 쓰고, 매일 도는 GitHub Actions가 둘을 서명해 릴리스로 게시합니다. 앱은 별도 저장소에 있습니다.

앱은 이 자료를 표시만 하고 이 자료로 어떤 동작도 하지 않습니다. 그래서 잘못된 파일로 일어날 수 있는 최악의 일은 틀린 내용이 표시되는 것이고, 여기의 검사는 그것을 막기 위한 것입니다. 검사에 실패하면 지난 정상 파일이 그대로 게시된 채 남습니다.

## 명령

```bash
./test_build.py && ./test_advisories.py          # 전체 테스트, 네트워크 없음
./test_build.py Normalize.test_a_release_line    # 테스트 하나 (unittest의 Class.method)
./build.py                                       # 받아서 검사하고 data/support.json을 덮어씀
./advisories.py                                  # data/advisories.json에 같은 작업: 약 1분, 메모리 6GB
```

린터, 빌드 단계, 의존성 파일은 없습니다. `build.py`, `advisories.py`와 테스트는 표준 라이브러리만 씁니다. `sign.py`는 `cryptography`가, 워크플로의 서명 확인은 `minisign`이 필요하며 CI는 둘 다 apt로 설치합니다.

`build.py`와 `advisories.py`는 추적 중인 파일을 실제 출처의 자료로 덮어쓰므로, 새 자료가 필요할 때만 실행합니다. `--force`는 지난 파일과의 비교(변화량 한도와 더 오래된 날짜 거부)를 건너뛰지만, `check()`의 형식 검사와 파일 크기 한도는 건너뛰지 않습니다.

`data/advisories.json`은 약 17MB이고(앱의 한도는 압축 전 32MB, 압축 후 16MB) 공지 하나가 한 줄이므로, 전체를 읽지 말고 검색합니다.

## 구조

스크립트는 `python3 -I`로 실행되므로(shebang과 워크플로 참고) 스크립트 디렉터리가 `sys.path`에 없습니다. 서로 import할 수 없어서 `build.py`와 `advisories.py`에 `Refused`, `check`, `refuse_large_changes`, `text_of`, `fetch`가 각각 따로 있고, 테스트도 대상을 `importlib`로 불러옵니다. 코드를 추가할 때도 이 방식을 유지합니다.

두 스크립트는 같은 순서로 동작하며, 어느 단계든 실패하면 `Refused`가 발생해 파일을 쓰지 않고 1로 종료합니다.

1. 출처에서 받습니다. 응답마다 크기 한도가 있습니다.
2. 정규화합니다. 엄격한 정규식에 맞는 값만 남기며, 출처 자료는 악의적일 수 있다고 봅니다(`hostile` 테스트 참고).
3. `check()`로 앱이 받아들이는 형식인지 검사합니다.
4. `refuse_large_changes()`로 `data/`에 있는 파일과 비교합니다.
5. `text_of()`로 제품이나 공지 하나를 한 줄씩 씁니다. 하루치 변화가 `git log -p`에서 짧게 읽히도록 한 것이므로 출력 형식을 바꾸지 않습니다.

**짧은 키.** 지원 자료의 릴리스 라인은 `c`(라인), `e`(종료일), `l`(최신), `x`(종료됨)를 씁니다. 공지의 범위는 `i`(시작, 포함), `a`(시작, 제외), `f`(수정된 버전), `l`(마지막 영향 버전)을 씁니다. `l`은 두 파일에서 뜻이 다릅니다.

**앱과의 약속.** 앱이 이 파일들을 파싱하며, `SCHEMA`와 정규식이 앱이 받아들이는 형식을 나타냅니다. 형식을 바꾸면 MyLocal 저장소도 함께 바꿔야 합니다.

**`advisories.py`의 커버리지.** `BITNAMI`, `MAVEN`, `GO`, `NPM` 표에 있는 제품은 `covered`로, 일치하는 공지가 없으면 "알려진 공지 없음"으로 표시할 수 있습니다. 그래서 표에 넣기 전에 제품의 공식 공지 목록과 대조합니다. `*_ALSO`, `PYPI`, `RUBYGEMS`, `PACKAGIST` 표와 NVD는 `partial`로, 일치하는 공지가 없어도 아무것도 말해 주지 않습니다. covered 표의 제품도 공지가 하나도 없으면 `finish()`가 partial로 내리고, 그러면 `refuse_large_changes`가 실행을 멈춥니다.

**제품 키.** 지원 자료에 제품이 있으면 그 이름(`nextjs`), 없으면 앱이 찾는 패키지 이름(`npm:vite`)입니다. 표에는 `npm:next`처럼 패키지 이름으로 적어 두면 `resolved()`가 `data/support.json`의 `scoped`로 바꿉니다. 앱은 `mylocal-core`의 `advisory_key`로 같은 키를 찾습니다. PyPI 이름은 `*.dist-info` 폴더 그대로 `_`를 씁니다. 표의 `group:*`는 그룹의 모든 패키지를 뜻하며, 모듈이 제품과 같은 번호를 쓰는 그룹에만 씁니다.

**`advisories.py`의 병합.** `Merged`는 레코드를 CVE로 합치고, CVE가 없으면 서로의 별칭으로 합칩니다. 심각도, 제목, 게시일은 먼저 들어온 값을 쓰고 본문은 가장 긴 값을 쓰므로, `OSV_DATA` 순서와 NVD를 마지막에 넣는 순서가 결과에 영향을 줍니다. NVD는 OSV에 없는 공지만 더하고, OSV에 있는 공지는 범위를 그대로 두고 빠진 심각도만 채웁니다.

**범위에서 버리는 것.** 끝이 없는 범위와 `0.0.0-`으로 시작하는 범위는 넣지 않습니다. 대부분 Go 모듈로 릴리스하지 않는 프로그램이나 이미 고쳐진 공지에서 나오는 값이고, 그대로 두면 최신 버전까지 취약하다고 표시됩니다. Bitnami의 Helm 차트 공지도 차트 번호를 쓰므로 뺍니다. 패키지를 표에 더할 때는 최신 버전에 새로 일치하는 공지가 늘지 않는지 확인합니다.

## 게시 (`.github/workflows/publish.yml`)

- 지원 자료가 실패하면 실행 전체가 멈춥니다. 공지 쪽 실패는 `continue-on-error`라서 지원 자료는 게시되고 지난 공지가 유지되며, 알리기 위해 실행이 마지막에 실패로 끝납니다.
- 앱이 압축을 풀기 전에 서명을 확인하므로 `advisories.json.gz`는 압축된 상태로 서명합니다. `support.json`은 그대로 서명합니다.
- 각 단계는 필요한 것만 받습니다. 서명 키는 서명 단계에만, 쓰기 토큰은 게시 단계에만 들어갑니다. 외부 액션은 커밋으로 고정한 `actions/checkout`뿐이고, 다른 도구는 apt로 설치합니다.
- 실행이 바뀐 자료를 `Data as of <date>`로 `main`에 직접 커밋하므로 `main`은 매일 움직입니다. 푸시 전에 pull합니다.
- 거부된 실행은 아무것도 쓰지 않으므로 그 시점에는 읽을 diff가 없습니다. 변화량 때문에 거부되었다면 로컬에서 `--force`로 스크립트를 실행해 `git diff`를 읽고, 정상이면 Actions에서 `force`를 켜고 다시 실행합니다.

공개 키가 앱에 들어 있으므로 키를 바꾸려면 앱 릴리스도 필요합니다. 절차는 `README.md`에 있습니다.
