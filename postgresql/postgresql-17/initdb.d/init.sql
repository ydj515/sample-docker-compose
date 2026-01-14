-- 'appdb'에 대한 권한을 가진 'myuser' 사용자를 생성합니다.
CREATE USER myuser WITH PASSWORD 'mypassword';
GRANT ALL PRIVILEGES ON DATABASE appdb TO myuser;

-- 필요 시, 초기 테이블 생성 및 데이터 삽입 쿼리를 추가할 수 있습니다.
