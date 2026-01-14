-- 'mydatabase'에 대한 모든 권한을 가진 'myuser' 사용자를 생성합니다.
-- '%'는 모든 호스트에서의 접근을 허용합니다.
CREATE USER 'myuser'@'%' IDENTIFIED BY 'mypassword';
GRANT ALL PRIVILEGES ON mydatabase.* TO 'myuser'@'%';
FLUSH PRIVILEGES;

-- 필요 시, 초기 테이블 생성 및 데이터 삽입 쿼리를 추가할 수 있습니다.