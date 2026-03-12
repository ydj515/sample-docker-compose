# MongoDB Single with mongo-express

MongoDB 단일 인스턴스와 `mongo-express`를 함께 실행하는 Docker Compose 예제입니다.

## 구성

- MongoDB: `8.0.19`
- mongo-express: `1.0.2`
- 데이터 영속성: Docker named volume `mongo_data`
- 기동 안정성: MongoDB `healthcheck` 적용

## 실행 방법

1. 예제 폴더로 이동합니다.

```bash
cd mongodb/mongodb-single
```

2. 환경 변수 파일을 준비합니다.

```bash
cp .env-sample .env
```

3. [`.env`](./.env) 파일에서 계정과 비밀번호를 원하는 값으로 변경합니다.

- `MONGO_ROOT_USERNAME`
- `MONGO_ROOT_PASSWORD`
- `MONGO_EXPRESS_BASICAUTH_USERNAME`
- `MONGO_EXPRESS_BASICAUTH_PASSWORD`

4. 컨테이너를 실행합니다.

```bash
docker compose up -d
```

5. 실행 상태를 확인합니다.

```bash
docker compose ps
```

## 접속 정보

- MongoDB
  - 호스트: `localhost`
  - 포트: `27017`
  - 관리자 사용자명 예시: `root`
  - 관리자 비밀번호 예시: `root`
- mongo-express
  - URL: [http://localhost:8081](http://localhost:8081)
  - 로그인 사용자명 예시: `admin`
  - 로그인 비밀번호 예시: `admin`

## 자주 쓰는 명령어

### 로그 확인

```bash
docker compose logs -f
```

### 종료

```bash
docker compose down
```

### 종료 후 볼륨까지 삭제

```bash
docker compose down -v
```

## 확인 포인트

- `mongo` 컨테이너가 `healthy` 상태인지 확인합니다.
- `mongo-express` 접속 시 Basic Auth 로그인 창이 보이면 정상입니다.
- MongoDB 초기 관리자 계정은 [`.env`](./.env) 값으로 생성됩니다.
- 기본 예제 계정은 `root/root`, `mongo-express` 로그인은 `admin/admin`입니다.

## 주의사항

> - `.env` 파일은 민감 정보를 포함하므로 저장소에 커밋하지 않는 것이 좋습니다.
> - 예제 비밀번호는 반드시 변경해서 사용하세요.
> - `mongo-express`는 개발 및 테스트 용도에 더 적합합니다.
