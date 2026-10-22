# Simulátor Hikvision NVR: ISAPI na portu 80, RTSP na portu 554. Pouze pro vývoj a demo.
FROM alexxit/go2rtc:1.9.14
RUN apk add --no-cache python3 tzdata
COPY start.py mock_isapi.py snapshot.jpg sample.mp4 /mock/
CMD ["python3", "-u", "/mock/start.py"]
