from flask import Flask, request, Response
app = Flask(__name__)

@app.route('/', methods=['GET','POST','PUT','PATCH','DELETE','OPTIONS'])
def echo():
    data = request.get_data()
    if not data:
        return Response('', status=200, content_type='text/plain')
    return Response(data, status=200, content_type='text/plain')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80)
