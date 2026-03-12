-- 현재 접속 중인 데이터베이스 이름을 psql 변수로 저장합니다.
-- docker-entrypoint 는 POSTGRES_DB 로 지정된 DB에 접속해 이 SQL 을 실행합니다.
SELECT current_database() AS app_db_name \gset

-- 애플리케이션용 계정을 생성합니다.
-- 샘플 구성에서는 단순성을 위해 계정명/비밀번호를 고정합니다.
CREATE USER myuser WITH PASSWORD 'mypassword';

-- 애플리케이션 계정에 데이터베이스 권한을 부여합니다.
GRANT ALL PRIVILEGES ON DATABASE :"app_db_name" TO myuser;

-- PostgreSQL 15+ 에서는 public 스키마 CREATE 권한도 함께 주는 편이 안전합니다.
GRANT USAGE, CREATE ON SCHEMA public TO myuser;
