# -*- coding: utf-8 -*-
"""
    moritz-server
    ~~~~~~~~~~~~~

    Sample HTTP Service providing current states of thermostats as well as command control interface to them

    :copyright: (c) 2014 by Markus Ullmann.
    :license: BSD, see LICENSE for more details.
"""

# environment constants

# python imports
from datetime import datetime
import Queue
import json
from json import encoder

# environment imports
from flask import Flask, request
from flask.ext.sqlalchemy import SQLAlchemy

# custom imports
from moritzprotocol.communication import CULMessageThread, CUBE_ID
from moritzprotocol.messages import SetTemperatureMessage

# local constantsfrom datetime import datetime
encoder.FLOAT_REPR = lambda o: format(o, '.2f')
THERMOSTATS = {
    0x0E023B: "Bad",
    0x0E04A6: "Schlafzimmer",
    0x0E016C: "Wohnzimmer",
}
THERMOSTATS_BY_NAME = dict((v,k) for k, v in THERMOSTATS.items())


class JSONWithDateEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        # Let the base class default method raise the TypeError
        return json.JSONEncoder.default(self, obj)

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////tmp/moritz-server.db'
db = SQLAlchemy(app)

def main(args):
    command_queue = Queue.Queue()
    message_thread = CULMessageThread(command_queue, args.cul_path)
    message_thread.start()


    @app.route("/")
    def index():
        with message_thread.thermostat_states_lock:
            return json.dumps(message_thread.thermostat_states, cls=JSONWithDateEncoder)

    @app.route("/set_temp", methods=["GET", "POST"])
    def set_temp():
        if not request.form:
            content = """<html><form action="" method="POST"><select name="thermostat">"""
            for thermo_id, thermo_name in THERMOSTATS.items():
                content += """<option value="%s">%s</option>""" % (thermo_id, thermo_name)
            content += """</select><select name="mode"><option>auto</option><option selected>manual</option><option>boost</option></select>"""
            content += """<input type=text name=temperature><input type=submit value="set"></form></html>"""
            return content
#
# Models
#
class Thermostat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer)
    serial = db.Column(db.String(32))
    firmware_version = db.Column(db.String(32), nullable=True)
    name = db.Column(db.String(64))
    paired = db.Column(db.Boolean, default=False)

    def __init__(self, sender_id, serial):
        self.sender_id = sender_id
        self.serial = serial
        self.name = serial

    def __repr__(self):
        return "<%s sender_id=%s name=%s>" % (self.__class__.__name__, self.sender_id, self.name)


class ThermostatState(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    thermostat_id = db.Column(db.Integer, db.ForeignKey('thermostat.id'))
    thermostat = db.relationship('Thermostat', backref=db.backref('states', lazy='dynamic'))
    last_updated = db.Column('last_updated', db.DateTime, onupdate=datetime.now)
    rferror = db.Column(db.Boolean, nullable=True)
    signal_strength = db.Column(db.Integer, nullable=True)
    desired_temperature = db.Column(db.Float, nullable=True)
    is_locked = db.Column(db.Boolean, nullable=True)
    valve_position = db.Column(db.Integer, nullable=True)
    lan_gateway = db.Column(db.Boolean, nullable=True)
    dstsetting = db.Column(db.Boolean, nullable=True)
    mode = db.Column(db.Integer, nullable=True)
    measured_temperature = db.Column(db.Float, nullable=True)
    battery_low = db.Column(db.Boolean, nullable=True)


        msg = SetTemperatureMessage()
        msg.counter = 0xB9
        msg.sender_id = CUBE_ID
        msg.receiver_id = int(request.form['thermostat'])
        msg.group_id = 0
        payload = {
            'desired_temperature': float(request.form["temperature"]),
            'mode': request.form["mode"],
        }
        command_queue.put((msg, payload))
        return """<html>Done. <a href="/">back</a>"""

    @app.route("/set_temp_all", methods=["GET", "POST"])
    def set_temp_all():
        if not request.form:
            content = """<html><form action="" method="POST"><select name="mode"><option>auto</option><option selected>manual</option><option>boost</option></select>"""
            content += """<input type=text name=temperature><input type=submit value="set"></form></html>"""
            return content
        for thermo_id in THERMOSTATS:
            msg = SetTemperatureMessage()
            msg.counter = 0xB9
            msg.sender_id = CUBE_ID
            msg.receiver_id = thermo_id
            msg.group_id = 0
            payload = {
                'desired_temperature': float(request.form["temperature"]),
                'mode': request.form["mode"],
            }
            command_queue.put((msg, payload))
        return """<html>Done. <a href="/">back</a>"""

    if args.flask_debug:
        app.run(host="0.0.0.0", port=12345, debug=True, use_reloader=False)
    else:
        app.run(host="0.0.0.0", port=12345)

    message_thread.join()

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--flask-debug", action="store_true", help="Enables Flask debug and reload. May cause weird behaviour.")
    parser.add_argument("--detach", action="store_true", help="Detach from terminal")
    parser.add_argument("--cul-path", default="/dev/ttyACM0", help="Path to usbmodem path of CUL, defaults to /dev/ttyACM0")
    args = parser.parse_args()

    db.create_all()

    if args.detach:
        import detach
        with detach.Detach(daemonize=True) as d:
            if d.pid:
                print("started process {} in background".format(d.pid))
            else:
                main(args)
    else:
        main(args)