# MySQL 개발환경

이 디렉터리는 MySQL 로컬 개발/학습용 Docker Compose 샘플을 정리한 폴더입니다.

## 구성

| 디렉터리                 | 구성 및 용도                                      | 기본 호스트 포트 |
|----------------------|----------------------------------------------|-----------|
| [mysql-8](mysql-8/) | MySQL 8.4 단일 노드 + 설정 파일(`conf.d`) + 초기화 SQL(`initdb.d`) | 3306      |

### mysql-8

- `conf.d/custom.cnf`
  - 서버/클라이언트 문자셋을 `utf8mb4`, collation을 `utf8mb4_unicode_ci`로 설정합니다.
  - 그 외 튜닝 항목은 주석으로 정리되어 있어 필요한 값만 활성화해서 사용합니다.
- `initdb.d/init.sql`
  - 애플리케이션용 계정 `myuser`를 생성하고 `MYSQL_DATABASE`로 지정한 DB에 전체 권한을 부여합니다.

## 사용 가이드

- 실행할 폴더로 이동한 뒤 `.env.example`을 `.env`로 복사합니다.
- `.env`에서 이미지, 호스트 포트, root 비밀번호, DB 이름, 시간대를 조정합니다.
- `.env`는 Git 추적에서 제외됩니다.
- 기본 비밀번호(`root`, `mypassword`)는 로컬 학습용입니다. 외부에 노출되는 환경에서는 반드시 변경합니다.
- `mysql_data` named volume을 사용하므로 `docker compose down`만으로는 데이터가 삭제되지 않습니다.
- 초기화 SQL은 빈 볼륨에서 처음 시작할 때만 실행합니다. 기존 볼륨의 계정·DB·비밀번호는 `.env` 수정만으로 변경되지 않습니다.

## 실행 예시

```bash
cd mysql-8
cp -n .env.example .env
docker compose config --quiet
docker compose up -d
docker compose exec mysql sh -c 'exec mysql -uroot -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"'
```

```sql
SELECT VERSION();
SHOW VARIABLES LIKE 'character_set_server';
```

### 종료 및 초기화

```bash
# 컨테이너와 네트워크 종료. 데이터 볼륨은 유지합니다.
docker compose down

# 데이터 볼륨까지 삭제합니다. 다음 기동 시 초기화 SQL이 다시 실행됩니다.
docker compose down -v
```
