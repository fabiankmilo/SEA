from kivy.config import Config

# Ajusta a 800x480 que es el estándar de las pantallas de 7"
Config.set('graphics', 'width', '800')
Config.set('graphics', 'height', '480')
Config.set('graphics', 'resizable', '0') # No permitir cambiar tamaño
#Config.set('graphics', 'fullscreen', 'auto') # Opcional: poner en pantalla completa

import threading
import time
import math
import serial

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.properties import NumericProperty, BooleanProperty, StringProperty
from kivy.clock import Clock
from kivy.lang import Builder

import RPi.GPIO as GPIO

# --- CONFIGURACIÓN HARDWARE MÁQUINA (SEA) ---
PIN_SENSOR = 24    # Entrada Sensor Inductivo
PIN_ACTUADOR = 23  # Salida Actuador Perforador

# --- PARAMETRIZACIÓN DEL MOTOR (Extraído de tu test_control_position.py) ---
DIAMETRO_RUEDA_M = 0.254
PPR = 16384
CIRCUNFERENCIA = math.pi * DIAMETRO_RUEDA_M
PULSOS_POR_METRO = PPR / CIRCUNFERENCIA

# --- VARIABLES DE CONTROL MODBUS MODIFICADO PARA LINUX/RPI ---
PORT = '/dev/ttyUSB0'  # Cambiado de 'COM9' a puerto típico de Raspberry Pi
BAUDRATE = 115200
SLAVE_ID = 1
RAMPA_MS = 400
VEL_RPM = 150

class RootWidget(BoxLayout):
    conteo_pasos = NumericProperty(0)
    ciclo_activo = BooleanProperty(False)
    sensor_on = BooleanProperty(False)
    actuador_on = BooleanProperty(False)
    estado_texto = StringProperty("ESTADO: LISTO PARA INICIAR")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Configurar GPIOs
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(PIN_SENSOR, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(PIN_ACTUADOR, GPIO.OUT)
        GPIO.output(PIN_ACTUADOR, GPIO.HIGH)

        # Atributo para almacenar el puerto serial persistente
        self.ser = None

        # Monitorear sensor en tiempo real en la UI
        Clock.schedule_interval(self.check_sensor_ui, 0.05)

    def check_sensor_ui(self, dt):
        self.sensor_on = GPIO.input(PIN_SENSOR) == GPIO.LOW

    # --- FUNCIONES AUXILIARES DE CÁLCULO MODBUS ---
    def calcular_crc(self, data):
        crc = 0xFFFF
        for pos in data:
            crc ^= pos
            for i in range(8):
                if (crc & 1) != 0:
                    crc >>= 1
                    crc ^= 0xA001
                else:
                    crc >>= 1
        return crc.to_bytes(2, 'little')

    def enviar_trama(self, trama_base):
        if self.ser and self.ser.is_open:
            trama_completa = trama_base + self.calcular_crc(trama_base)
            self.ser.write(trama_completa)
            time.sleep(0.04)

    def int_a_4bytes(self, n):
        b = n.to_bytes(4, 'big', signed=True)
        return b[0:2], b[2:4]

    # --- LÓGICA DE CONTROL ---
    def iniciar_ciclo(self):
        if not self.ciclo_activo:
            try:
                # Intentar abrir conexión serial única antes de arrancar el hilo
                self.ser = serial.Serial(PORT, BAUDRATE, timeout=1)
                self.ciclo_activo = True
                threading.Thread(target=self.logica_maquina, daemon=True).start()
            except Exception as e:
                self.estado_texto = f"ERROR SERIAL: No se pudo abrir {PORT}. {str(e)}"

    def detener_ciclo(self):
        self.ciclo_activo = False
        self.estado_texto = "ESTADO: DETENIENDO SISTEMA..."
        GPIO.output(PIN_ACTUADOR, GPIO.HIGH)
        self.actuador_on = False

        # Enviar comando de deshabilitación de emergencia por seguridad (0x0007)
        if self.ser and self.ser.is_open:
            self.enviar_trama(bytearray([SLAVE_ID, 0x06, 0x20, 0x0E, 0x00, 0x07]))
            self.ser.close()
        self.estado_texto = "ESTADO: DETENIDO Y DESHABILITADO"

    def logica_maquina(self):
        try:
            # 1. Esperar 3 segundos tras pulsar inicio por primera vez
            self.estado_texto = "ESTADO: ESPERANDO INICIO (3s)..."
            time.sleep(3)

            while self.ciclo_activo:
                if not self.ciclo_activo: break

                # 2. Activar Actuador (Perforar tierra)
                self.estado_texto = "ESTADO: PERFORANDO..."
                self.actuador_on = True
                GPIO.output(PIN_ACTUADOR, GPIO.LOW)

                # 3. Esperar señal física del sensor inductivo
                self.estado_texto = "ESTADO: ESPERANDO SENSOR INDUCTIVO..."
                while GPIO.input(PIN_SENSOR) == GPIO.HIGH:
                    if not self.ciclo_activo: break
                    time.sleep(0.02)

                if not self.ciclo_activo: break

                # Acción tras detectar sensor:
                self.conteo_pasos += 1
                self.actuador_on = False
                GPIO.output(PIN_ACTUADOR, GPIO.HIGH) # Apagar actuador

                # 4. Esperar 1 segundos antes de avanzar 10 cm
                self.estado_texto = "ESTADO: PAUSA PRE-AVANCE (2s)..."
                time.sleep(1)
                if not self.ciclo_activo: break

                # 5. Avanzar los 10 cm exactos mediante Modbus RTU
                self.estado_texto = "ESTADO: AVANZANDO 10 CM..."
                self.mover_motor_zltech(0.1) # Envía 0.1 metros (10 cm)

                if not self.ciclo_activo: break

                # 6. Esperar 4 segundos tras el posicionamiento completo
                self.estado_texto = "ESTADO: PAUSA POST-AVANCE (2s)..."
                time.sleep(4)

        except Exception as e:
            self.estado_texto = f"ERROR EN CICLO: {str(e)}"
            self.detener_ciclo()

    def mover_motor_zltech(self, metros):
        # Conversión matemática según tus ruedas de 10 pulgadas
        pulsos_base = int(metros * PULSOS_POR_METRO)
        pulsos_izq = pulsos_base
        pulsos_der = -pulsos_base

        # 1. Modo Sincronizado y Modo Relativo
        self.enviar_trama(bytearray([SLAVE_ID, 0x06, 0x20, 0x0F, 0x00, 0x01]))
        self.enviar_trama(bytearray([SLAVE_ID, 0x06, 0x20, 0x0D, 0x00, 0x01]))

        # 2. Configurar RAMPAS VARIABLE
        r_bytes = RAMPA_MS.to_bytes(2, 'big')
        for reg in [0x80, 0x81, 0x82, 0x83]:
            self.enviar_trama(bytearray([SLAVE_ID, 0x06, 0x20, reg]) + r_bytes)

        # 3. Velocidad de crucero perfil de posicionamiento
        v_bytes = VEL_RPM.to_bytes(2, 'big')
        self.enviar_trama(bytearray([SLAVE_ID, 0x06, 0x20, 0x8E]) + v_bytes)
        self.enviar_trama(bytearray([SLAVE_ID, 0x06, 0x20, 0x8F]) + v_bytes)

        # 4. Enable del Driver (Comando 0x0008)
        self.enviar_trama(bytearray([SLAVE_ID, 0x06, 0x20, 0x0E, 0x00, 0x08]))
        time.sleep(0.05)

        # 5. Inyección de posiciones en registro continuo (0x208A)
        h_izq, l_izq = self.int_a_4bytes(pulsos_izq)
        h_der, l_der = self.int_a_4bytes(pulsos_der)
        trama_pos = bytearray([SLAVE_ID, 0x10, 0x20, 0x8A, 0x00, 0x04, 0x08])
        trama_pos += h_izq + l_izq + h_der + l_der
        self.enviar_trama(trama_pos)

        # 6. ¡Disparo del Movimiento (START)!
        self.enviar_trama(bytearray([SLAVE_ID, 0x06, 0x20, 0x0E, 0x00, 0x10]))

        # Calcular tiempo de viaje físico estimado para mantener bloqueado el hilo de control
        tiempo_viaje = (abs(metros) / (CIRCUNFERENCIA * (VEL_RPM/60))) + (RAMPA_MS/1000) + 0.5
        time.sleep(tiempo_viaje)

class SeaApp(App):
    def build(self):
        # Carga explícita para evitar fallos de renderizado
        #Builder.load_file('sea.kv')
        return RootWidget()

if __name__ == '__main__':
    try:
        SeaApp().run()
    finally:
        GPIO.cleanup()
