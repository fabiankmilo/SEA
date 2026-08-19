import os
# CONFIG PARA EVITAR PANTALLA DIVIDIDA Y ERRORES DE VIDEO ---
os.environ['KIVY_WINDOW'] = 'sdl2'
os.environ['KIVY_GL_BACKEND'] = 'gl'

import threading
import time
import math
import serial

from kivy.config import Config
# Resolución forzada para pantalla de 7 pulgadas
Config.set('graphics', 'width', '800')
Config.set('graphics', 'height', '480')
Config.set('graphics', 'resizable', '0')
Config.set('graphics', 'fullscreen', '0') 

from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.properties import NumericProperty, BooleanProperty, StringProperty
from kivy.clock import Clock
from kivy.lang import Builder
import RPi.GPIO as GPIO

# CONFIGURACIÓN HARDWARE SEA ---
PIN_SENSOR = 24    # Entrada Sensor Inductivo
PIN_ACTUADOR = 23  # Salida Actuador Perforador

# PARAMETRIZACIÓN DE LOS MOTORES
DIAMETRO_RUEDA_M = 0.254 
PPR = 16384  
CIRCUNFERENCIA = math.pi * DIAMETRO_RUEDA_M
PULSOS_POR_METRO = PPR / CIRCUNFERENCIA

# VARIABLES DE CONTROL MODBUS
PORT = '/dev/ttyUSB0'  # puerto para linux
BAUDRATE = 115200
SLAVE_ID = 1
RAMPA_MS = 400  
VEL_RPM = 150     

class PantallaPrincipal(Screen):
    # Variables exclusivas de la pantalla principal
    conteo_pasos = NumericProperty(0)
    ciclo_activo = BooleanProperty(False)
    sensor_on = BooleanProperty(False)
    actuador_on = BooleanProperty(False)
    estado_texto = StringProperty("ESTADO: LISTO PARA INICIAR")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Configuración de pines GPIO (tener en cuenta que usamos LOW = ON - HIGH = OFF)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(PIN_SENSOR, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(PIN_ACTUADOR, GPIO.OUT)
        GPIO.output(PIN_ACTUADOR, GPIO.HIGH)
        
        self.ser = None
        Clock.schedule_interval(self.check_sensor_ui, 0.05)

    def check_sensor_ui(self, dt):
        self.sensor_on = GPIO.input(PIN_SENSOR) == GPIO.LOW

    # Caluclo CRC protocolo MODBUS RTU
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

    # Inicio de conexion serial RS-485
    def iniciar_ciclo(self):
        if not self.ciclo_activo:
            try:
                # Se abre la conexión serial de forma persistente
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
        
        # Deshabilitar motor (quitar holding torque) al detener
        if self.ser and self.ser.is_open:
            self.enviar_trama(bytearray([SLAVE_ID, 0x06, 0x20, 0x0E, 0x00, 0x07]))
            self.ser.close()
        self.estado_texto = "ESTADO: DETENIDO Y DESHABILITADO"

    def logica_maquina(self):
        try:
            self.estado_texto = "ESTADO: ESPERANDO INICIO (3s)..."
            time.sleep(3)
            
            while self.ciclo_activo:
                if not self.ciclo_activo: break

                self.estado_texto = "ESTADO: PERFORANDO..."
                self.actuador_on = True
                GPIO.output(PIN_ACTUADOR, GPIO.LOW)
                
                self.estado_texto = "ESTADO: ESPERANDO SENSOR INDUCTIVO..."
                while GPIO.input(PIN_SENSOR) == GPIO.HIGH:
                    if not self.ciclo_activo: break
                    time.sleep(0.02)
                
                if not self.ciclo_activo: break
                
                self.conteo_pasos += 1
                self.actuador_on = False
                GPIO.output(PIN_ACTUADOR, GPIO.HIGH) 
                
                self.estado_texto = "ESTADO: PAUSA PRE-AVANCE (2s)..."
                time.sleep(2) # este es el tiempo de pausa para que los operarios introduzcan el esqueje
                if not self.ciclo_activo: break
                
                # --- AQUÍ SE OBTIENE LA DISTANCIA DINÁMICA DE LA APLICACIÓN GLOBAL ---
                app_global = App.get_running_app()
                distancia_cm = app_global.distancia_avance_cm
                avance_metros = distancia_cm / 100.0 
                
                self.estado_texto = f"ESTADO: AVANZANDO {distancia_cm} CM..."
                self.mover_motor_zltech(avance_metros) 
                
                if not self.ciclo_activo: break
                
                # este es el tiempo que hay que calibrar 
                self.estado_texto = "ESTADO: PAUSA POST-AVANCE (4s)..."
                time.sleep(4)

        except Exception as e:
            self.estado_texto = f"ERROR EN CICLO: {str(e)}"
            self.detener_ciclo()

    def mover_motor_zltech(self, metros):
        pulsos_base = int(metros * PULSOS_POR_METRO)
        pulsos_izq = pulsos_base
        pulsos_der = -pulsos_base 

        self.enviar_trama(bytearray([SLAVE_ID, 0x06, 0x20, 0x0F, 0x00, 0x01]))
        self.enviar_trama(bytearray([SLAVE_ID, 0x06, 0x20, 0x0D, 0x00, 0x01]))
        
        r_bytes = RAMPA_MS.to_bytes(2, 'big')
        for reg in [0x80, 0x81, 0x82, 0x83]:
            self.enviar_trama(bytearray([SLAVE_ID, 0x06, 0x20, reg]) + r_bytes)

        v_bytes = VEL_RPM.to_bytes(2, 'big')
        self.enviar_trama(bytearray([SLAVE_ID, 0x06, 0x20, 0x8E]) + v_bytes)
        self.enviar_trama(bytearray([SLAVE_ID, 0x06, 0x20, 0x8F]) + v_bytes)

        self.enviar_trama(bytearray([SLAVE_ID, 0x06, 0x20, 0x0E, 0x00, 0x08]))
        time.sleep(0.05)

        h_izq, l_izq = self.int_a_4bytes(pulsos_izq)
        h_der, l_der = self.int_a_4bytes(pulsos_der)
        trama_pos = bytearray([SLAVE_ID, 0x10, 0x20, 0x8A, 0x00, 0x04, 0x08])
        trama_pos += h_izq + l_izq + h_der + l_der
        self.enviar_trama(trama_pos)

        self.enviar_trama(bytearray([SLAVE_ID, 0x06, 0x20, 0x0E, 0x00, 0x10]))

        tiempo_viaje = (abs(metros) / (CIRCUNFERENCIA * (VEL_RPM/60))) + (RAMPA_MS/1000) + 0.5
        time.sleep(tiempo_viaje)

class PantallaConfiguracion(Screen):
    # La interfaz y botones se manejan directamente desde el archivo sea.kv
    pass

class VentanaManager(ScreenManager):
    pass

class SeaApp(App):
    # --- VARIABLE GLOBAL DE LA APLICACIÓN ---
    # Al estar aquí, cualquier pantalla en el archivo .kv puede acceder a ella usando "app.distancia_avance_cm"
    # y cualquier hilo de Python puede acceder con "App.get_running_app().distancia_avance_cm"
    distancia_avance_cm = NumericProperty(10)

    def build(self):
        # Asegúrate de que tu archivo de diseño se siga llamando 'sea.kv' y esté en la misma carpeta
        Builder.load_file('sea.kv')
        # Retornamos el administrador de pantallas que ya contiene las pantallas declaradas en el .kv
        return VentanaManager()

if __name__ == '__main__':
    try:
        SeaApp().run()
    except KeyboardInterrupt:
        print("\nPrograma detenido manualmente.")
    finally:
        # Asegurarse de liberar los pines de la Raspberry al salir
        GPIO.cleanup()