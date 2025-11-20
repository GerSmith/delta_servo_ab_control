import time
import yaml
import minimalmodbus

JOG_STEP = 25  # Шаг изменения скорости в JOG режиме


class ServoController:
    """Класс для управления сервоприводом Delta ASDA-AB по Modbus RTU"""

    # Адреса регистров для основных операций
    REGISTERS = {
        "VERSION": 0,  # P0-00 - Версия ПО
        "ERROR": 1,  # P0-01 - Код ошибки
        "JOG": 1029,  # P4-05 - Управление JOG, 0405H (hex) == 1029 dec
    }

    # Команды JOG
    JOG_COMMANDS = {
        "FORWARD": 4999,  # Вперед
        "REVERSE": 4998,  # Назад
        "STOP": 5000,  # Остановка
        "SPEED_MIN": 0,  # Минимальная скорость
        "SPEED_MAX": 3000,  # Максимальная скорость
    }

    def __init__(self, config_file="modbus_config.yaml"):
        """Инициализация контроллера с загрузкой конфигурации"""
        self.instrument = None
        self.config = self._load_config(config_file)
        self.current_speed = 20  # Начальная скорость в об/мин
        self.current_direction = None  # None - остановлен, "forward" или "reverse"

    def _load_config(self, config_file):
        """Загрузка конфигурации из YAML файла"""
        try:
            with open(config_file, "r") as file:
                config = yaml.safe_load(file)
                return config.get("modbus", {})
        except FileNotFoundError:
            print(f"❌ Ошибка: Файл конфигурации {config_file} не найден")
            raise
        except Exception as e:
            print(f"❌ Ошибка при загрузке конфигурации: {e}")
            raise

    def connect(self):
        """Установка соединения с сервоприводом"""
        try:
            # Создаем объект инструмента Modbus
            self.instrument = minimalmodbus.Instrument(
                self.config["port"], self.config["slave_address"]
            )

            # Настраиваем параметры serial порта
            self.instrument.serial.baudrate = self.config["baudrate"]
            self.instrument.serial.bytesize = self.config["bytesize"]
            self.instrument.serial.parity = self.config["parity"]
            self.instrument.serial.stopbits = self.config["stopbits"]
            self.instrument.serial.timeout = self.config["timeout"]

            print(
                f"✅ Успешное подключение к {self.config['port']} на скорости {self.config['baudrate']} baud"
            )
            return True

        except Exception as e:
            print(f"❌ Не удалось подключиться: {e}")
            print("Проверьте:")
            print("- Правильность COM-порта")
            print("- Скорость передачи (должна быть 9600 для P3-01=1)")
            print("- Параметр P3-02 должен быть установлен в 7 (Modbus RTU, 8,E,1)")
            print("- Физическое подключение RS-485")
            return False

    def check_connection(self):
        """Проверка связи с сервоприводом"""
        try:
            # Читаем версию прошивки (P0-00)
            version = self.instrument.read_register(self.REGISTERS["VERSION"], functioncode=3)

            # Читаем код ошибки (P0-01)
            error_code = self.instrument.read_register(self.REGISTERS["ERROR"], functioncode=3)

            print(f"🔍 Связь установлена!")
            print(f"   Версия ПО: {version}")

            # Проверка кода ошибки
            if error_code == 0:
                print("✅ Отсутствуют ошибки (код 0)")
            else:
                print(f"⚠️  Обнаружена ошибка! Код: {error_code}")
                # Справочная информация по основным кодам ошибок
                error_descriptions = {
                    1: "Перегрузка по току",
                    2: "Перенапряжение",
                    3: "Пониженное напряжение",
                    4: "Смещение Z-импульса",
                    5: "Ошибка рекуперации",
                    6: "Перегрузка",
                    7: "Превышение скорости",
                    8: "Некорректная команда импульсного управления",
                    9: "Чрезмерное отклонение",
                    10: "Ошибка watchdog",
                    13: "Активирован аварийный останов",
                    14: "Ошибка обратного предела",
                    15: "Ошибка прямого предела",
                    20: "Ошибка последовательной связи",
                    23: "Предупреждение о перегрузке",
                }
                description = error_descriptions.get(error_code, "Неизвестная ошибка")
                print(f"   Описание: {description}")
                print("   Необходимо устранить ошибку перед управлением")
                return False

            return True

        except Exception as e:
            print(f"❌ Ошибка при проверке связи: {e}")
            return False

    def initialize_speed(self):
        """Чтение текущей скорости JOG с сервопривода при запуске"""
        try:
            # Читаем текущее значение скорости из регистра P4-05
            current_speed = self.instrument.read_register(self.REGISTERS["JOG"], functioncode=3)
            # Проверяем, является ли значение корректной скоростью (а не командой движения)
            if current_speed <= self.JOG_COMMANDS["SPEED_MAX"]:
                self.current_speed = current_speed
                print(f"📊 Текущая скорость JOG считана из сервопривода: {self.current_speed} об/мин")
            else:
                print(
                    f"ℹ️  Текущее значение регистра P4-05 ({current_speed}) не является скоростью. Используется начальное значение 20 об/мин."
                )
        except Exception as e:
            print(f"⚠️  Не удалось прочитать текущую скорость: {e}")
            print("ℹ️  Используется начальное значение скорости (20 об/мин).")

    def set_jog_speed(self, speed):
        """Установка скорости для режима JOG с применением на лету"""
        try:
            # Проверка диапазона скорости
            if speed < self.JOG_COMMANDS["SPEED_MIN"]:
                speed = self.JOG_COMMANDS["SPEED_MIN"]
            elif speed > self.JOG_COMMANDS["SPEED_MAX"]:
                speed = self.JOG_COMMANDS["SPEED_MAX"]

            # Записываем скорость в регистр P4-05
            self.instrument.write_register(self.REGISTERS["JOG"], speed, functioncode=6)
            self.current_speed = speed

            # Если мотор в движении, продолжаем движение в том же направлении
            if self.current_direction == "forward":
                self.jog(self.JOG_COMMANDS["FORWARD"])
            elif self.current_direction == "reverse":
                self.jog(self.JOG_COMMANDS["REVERSE"])

            print(f"🎯 Скорость установлена: {speed} об/мин")
            return True
        except Exception as e:
            print(f"❌ Ошибка при установке скорости JOG: {e}")
            return False

    def increase_speed(self, increment=JOG_STEP):
        """Увеличение скорости JOG на указанную величину"""
        new_speed = self.current_speed + increment
        return self.set_jog_speed(new_speed)

    def decrease_speed(self, decrement=JOG_STEP):
        """Уменьшение скорости JOG на указанную величину"""
        new_speed = self.current_speed - decrement
        return self.set_jog_speed(new_speed)

    def jog(self, command):
        """Управление режимом JOG с отслеживанием направления"""
        try:
            # Записываем команду в регистр P4-05
            self.instrument.write_register(self.REGISTERS["JOG"], command, functioncode=6)

            # Обновляем текущее направление движения
            if command == self.JOG_COMMANDS["FORWARD"]:
                self.current_direction = "forward"
            elif command == self.JOG_COMMANDS["REVERSE"]:
                self.current_direction = "reverse"
            elif command == self.JOG_COMMANDS["STOP"]:
                self.current_direction = None

            return True
        except Exception as e:
            print(f"❌ Ошибка при отправке JOG команды: {e}")
            return False

    def stop_jog(self):
        """Остановка вращения в режиме JOG"""
        self.current_direction = None
        return self.jog(self.JOG_COMMANDS["STOP"])

    def reset_speed_to_initial(self):
        """Сброс скорости до начального значения"""
        try:
            self.set_jog_speed(20)  # Сбрасываем до 20 об/мин
            print("🔄 Скорость сброшена до начального значения (20 об/мин)")
            return True
        except Exception as e:
            print(f"❌ Не удалось сбросить скорость: {e}")
            return False

    def close(self):
        """Закрытие соединения"""
        if self.instrument:
            self.stop_jog()
            # Сбрасываем скорость до начального значения перед закрытием
            self.reset_speed_to_initial()
            print("⏹️  Остановлено и соединение закрыто")


def main():
    """Основная функция управления"""
    print("=" * 50)
    print("Delta ASDA-AB Servo Controller - JOG Mode")
    print("=" * 50)

    # Инициализация контроллера
    controller = ServoController()

    # Подключение к устройству
    if not controller.connect():
        return

    # Проверка связи
    if not controller.check_connection():
        controller.close()
        return

    # Инициализация скорости при запуске
    controller.initialize_speed()

    print("\n" + "=" * 50)
    print("✅ Готов к управлению!")
    print(f"Текущая скорость: {controller.current_speed} об/мин")
    print("Управление:")
    print("  w - Вращение вперед (CW)")
    print("  s - Вращение назад (CCW)")
    print("  пробел - Остановить вращение")
    print(f"  + - Увеличить скорость на {JOG_STEP} об/мин")
    print(f"  - - Уменьшить скорость на {JOG_STEP} об/мин")
    print("  q - Выход из программы")
    print("=" * 50)

    try:
        while True:
            # Ожидание команды пользователя
            command = input("Введите команду: ").strip().lower()

            if command == "w":
                controller.jog(controller.JOG_COMMANDS["FORWARD"])
                print(f"➡️  Вращение ВПЕРЕД ({controller.current_speed} об/мин)")

            elif command == "s":
                controller.jog(controller.JOG_COMMANDS["REVERSE"])
                print(f"⬅️  Вращение НАЗАД ({controller.current_speed} об/мин)")

            elif command == " " or command == "":
                controller.stop_jog()
                print("⏹️  Остановлено")

            elif command == "+":
                controller.increase_speed(JOG_STEP)
                print(f"📈 Скорость увеличена: {controller.current_speed} об/мин")

            elif command == "-":
                controller.decrease_speed(JOG_STEP)
                print(f"📉 Скорость уменьшена: {controller.current_speed} об/мин")

            elif command == "q":
                print("\n👋 Выход из программы...")
                break

            else:
                print("❌ Неизвестная команда. Используйте w, s, пробел, +, - или q.")

            # Небольшая задержка для плавной работы
            time.sleep(0.1)

    except KeyboardInterrupt:
        print("\n⚠️  Программа прервана пользователем")

    finally:
        # Сбрасываем скорость до начального значения перед выходом
        controller.close()


if __name__ == "__main__":
    main()
