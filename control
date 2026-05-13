import threading
import time
from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.properties import NumericProperty, BooleanProperty, StringProperty
from kivy.clock import Clock
import RPi.GPIO as GPIO

# Configuración de Pines
PIN_SENSOR = 18    # Entrada Sensor Inductivo
PIN_ACTUADOR = 23  # Salida Actuador Perforador

class RootWidget(BoxLayout):
    conteo_pasos = NumericProperty(0)
    ciclo_activo = BooleanProperty(False)
    sensor_on = BooleanProperty(False)
    actuador_on = BooleanProperty(False)
    estado_texto = StringProperty("ESTADO: LISTO PARA INICIAR")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Configurar GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(PIN_SENSOR, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        GPIO.setup(PIN_ACTUADOR, GPIO.OUT)
        GPIO.output(PIN_ACTUADOR, GPIO.LOW)
        
        # Monitorear el sensor constantemente (UI update)
        Clock.schedule_interval(self.check_sensor_ui, 0.1)

    def check_sensor_ui(self, dt):
        self.sensor_on = GPIO.input(PIN_SENSOR) == GPIO.HIGH

    def iniciar_ciclo(self):
        if not self.ciclo_activo:
            self.ciclo_activo = True
            # Ejecutar lógica en un hilo separado para no bloquear la HMI
            threading.Thread(target=self.logica_maquina, daemon=True).start()

    def detener_ciclo(self):
        self.ciclo_activo = False
        self.estado_texto = "ESTADO: DETENIENDO..."
        GPIO.output(PIN_ACTUADOR, GPIO.LOW)

    def logica_maquina(self):
        try:
            while self.ciclo_activo:
                # 1. Esperar 3 segundos tras inicio
                self.estado_texto = "ESTADO: ESPERANDO INICIO (3s)..."
                time.sleep(3)
                if not self.ciclo_activo: break

                # 2. Activar Actuador
                self.estado_texto = "ESTADO: PERFORANDO..."
                self.actuador_on = True
                GPIO.output(PIN_ACTUADOR, GPIO.HIGH)
                
                # 3. Esperar señal del sensor inductivo
                self.estado_texto = "ESTADO: ESPERANDO SENSOR..."
                while GPIO.input(PIN_SENSOR) == GPIO.LOW:
                    if not self.ciclo_activo: break
                    time.sleep(0.05)
                
                if not self.ciclo_activo: break
                
                # Al recibir señal:
                self.conteo_pasos += 1
                self.actuador_on = False
                GPIO.output(PIN_ACTUADOR, GPIO.LOW)
                
                # 4. Esperar 2 segundos antes de avanzar
                self.estado_texto = "ESTADO: PAUSA PRE-AVANCE (2s)..."
                time.sleep(2)
                
                # 5. Avanzar 10 cm (Aquí llamas a tu función Modbus de ZLTech)
                self.estado_texto = "ESTADO: AVANZANDO 10CM..."
                self.mover_motor_zltech() 
                
                # 6. Esperar 2 segundos tras detenerse
                self.estado_texto = "ESTADO: PAUSA POST-AVANCE (2s)..."
                time.sleep(2)

            self.estado_texto = "ESTADO: DETENIDO"
        except Exception as e:
            self.estado_texto = f"ERROR: {str(e)}"

    def mover_motor_zltech(self):
        # Aquí insertas el código Modbus que ya probamos
        # client.write_register(0x2001, 1304, unit=1)
        print("Motor moviéndose 10cm...")
        time.sleep(1) # Simulación de tiempo de movimiento

class SeaApp(App):
    def build(self):
        return RootWidget()

if __name__ == '__main__':
    try:
        SeaApp().run()
    finally:
        GPIO.cleanup()
