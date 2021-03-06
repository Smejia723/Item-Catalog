# imports parts from python
import httplib2
import json
import requests
import random
import string
#imports from flask webdevelopment framework for Python
from flask import Flask
from flask import render_template
from flask import request
from flask import redirect
from flask import jsonify
from flask import url_for
from flask import flash
from database_setup import Base
from database_setup import Restaurant
from database_setup import MenuItem
from database_setup import User
# impirts from SQLAlchemy, Python SQL toolkit
from sqlalchemy import create_engine
from sqlalchemy import asc
from sqlalchemy.orm import sessionmaker

# New Imports for anti forgery
from flask import session as login_session

# Imports for client secrets
from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError
from flask import make_response


app = Flask(__name__)

CLIENT_ID = json.loads(
    open('client_secret_.json', 'r').read())['web']['client_id']
# Create session and connect to DB
engine = create_engine('sqlite:///restaurantmenu.db')
Base.metadata.bind = engine
DBSession = sessionmaker(bind=engine)
session = DBSession()


# Creats a state token to prevent un-user requests
# Store it in session for later validation
@app.route('/login')
def showLogin():
    state = ''.join(random.choice(string.ascii_uppercase + string.digits)
                    for x in xrange(32))
    login_session['state'] = state
    # Rendering login template
    return render_template('login.html', STATE=state)


@app.route('/gconnect', methods=['POST'])
def gconnect():
    # Validate state token
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    # Obtain authorization code
    code = request.data

    try:
        # Upgrade the authorization code into a credentials object
        oauth_flow = flow_from_clientsecrets('client_secret_.json', scope='')
        oauth_flow.redirect_uri = 'postmessage'
        credentials = oauth_flow.step2_exchange(code)
    except FlowExchangeError:
        response = make_response(
            json.dumps('Failed to upgrade the authorization code.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Check that the access token is valid.
    access_token = credentials.access_token
    url = (
        'https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s'
        % access_token
        )
    h = httplib2.Http()
    result = json.loads(h.request(url, 'GET')[1])
    # If there was an error in the access token info, abort.
    if result.get('error') is not None:
        response = make_response(json.dumps(result.get('error')), 500)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is used for the intended user.
    gplus_id = credentials.id_token['sub']
    if result['user_id'] != gplus_id:
        response = make_response(
            json.dumps("Token's user ID doesn't match given user ID."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is valid for this app.
    if result['issued_to'] != CLIENT_ID:
        response = make_response(
            json.dumps("Token's client ID does not match app's."), 401)
        print "Token's client ID does not match app's."
        response.headers['Content-Type'] = 'application/json'
        return response

    # Check to see if user is already logged in
    stored_access_token = login_session.get('access_token')
    stored_gplus_id = login_session.get('gplus_id')
    if stored_access_token is not None and gplus_id == stored_gplus_id:
        response = make_response(json.dumps(
            'Current user is already connected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Store the access token in the session for later use.
    login_session['access_token'] = credentials.access_token
    login_session['gplus_id'] = gplus_id

    # Get user info
    userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    params = {'access_token': credentials.access_token, 'alt': 'json'}
    answer = requests.get(userinfo_url, params=params)

    data = answer.json()
    login_session['provider'] = 'google'
    login_session['username'] = data['name']
    login_session['picture'] = data['picture']
    login_session['email'] = data['email']

    # see if user exists, if it doesn't make a new one!
    user_id = getUserID(login_session['email'])
    if not user_id:
        user_id = createUser(login_session)
    login_session['user_id'] = user_id

    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']
    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']

    output += ' " <style = "width: 300px; height: 300px;border-radius: 150px;-\
    webkit-border-radius: 150px;-moz-border-radius: 150px;>"'

    flash("you are now logged in as %s" % login_session['username'])
    print "done!"
    return output


# DISCONNECT- Revoke a current user's doken and reset there login_session.
@app.route("/gdisconnect")
def gdisconnect():
    access_token = login_session.get('access_token')
    if access_token is None:
        print 'Access Token is None'
        response = make_response(
            json.dumps('Current user not connected.'),
            401
            )
        response.headers['Content-Type'] = 'application/json'
        return response
    print 'In gdisconnect access token is %s', access_token
    print 'User name is: '
    print login_session['username']
    url = 'https://accounts.google.com/o/oauth2/revoke?token=%s' % login_session[('access_token')]
    h = httplib2.Http()
    result = h.request(url, 'GET')[0]
    print 'result is '
    print result
    if result['status'] == '200':
        del login_session['access_token']
        del login_session['gplus_id']
        del login_session['username']
        del login_session['email']
        del login_session['picture']
        response = make_response(json.dumps('Successfully disconnected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return redirect(url_for('showRestaurants'))
    else:
        response = make_response(json.dumps(
            'Failed to revoke token for given user.', 400)
            )
        response.headers['Content-Type'] = 'application/json'
        return response

# JSON for Database to colect info on restaurants
@app.route('/restaurants/JSON')
def restaurantsJSON():
    restaurants = session.query(Restaurant).all()
    return jsonify(restaurants=[r.serialize for r in restaurants])

# JSON for Database to colect info on items in restaurant Menus
@app.route('/restaurants/<int:restaurant_id>/menu/JSON')
def restaurantMenuJSON(restaurant_id):
    restaurants = session.query(
        Restaurant
        ).filter_by(id=restaurant_id).one()
    items = session.query(MenuItem).filter_by(
        restaurant_id=restaurants.id).all()
    return jsonify(MenuItems=[i.serialize for i in items])


@app.route('/restaurants/<int:restaurant_id>/menu/<int:menu_id>/JSON')
def menuItemJSON(restaurant_id, menu_id):
    MenuItem = session.query(MenuItem).filter_by(id=menu_id).one()
    return jsonify(Menu_Item=Menu_Item.serialize)
# Making an API Endpoint (Get Request)


@app.route('/')
@app.route('/restaurants/')
def showRestaurants():
    restaurants = session.query(Restaurant).order_by(Restaurant.name.asc())
#    print "restaurant", restaurants
#    for restaurant in restaurants:
#        print restaurant.name, restaurant.user_id
#    return "showRestaurants"
    if 'username' not in login_session:
        return render_template(
            'publicrestaurant.html',
            restaurants=restaurants
            )
    else:
        return render_template(
            'restaurant.html',
            restaurants=restaurants
            )


@app.route('/restaurants/new/', methods=['GET', 'POST'])
def newRestaurant():
    if 'username' not in login_session:
        return redirect('/login')
    if request.method == 'POST':
        newRestaurant = Restaurant(
            name=request.form['name'],
            user_id=login_session['user_id']
            )
        session.add(newRestaurant)
        session.commit()
        return redirect(url_for('showRestaurants'))
    else:
        return render_template('newRestaurant.html')


@app.route('/restaurants/<int:restaurant_id>/edit/', methods=['GET', 'POST'])
def editRestaurant(restaurant_id):
    if 'username' not in login_session:
        return redirect('/login')
    restaurant = session.query(Restaurant).filter_by(id = restaurant_id).one()
    editedRestaurant = session.query(
        Restaurant).filter_by(id=restaurant_id).one()
    if editedRestaurant.user_id != login_session['user_id']:
        return "<script>\
        {alert('You are not authorized to edit this restaurant. \
        Please create your own restaurant.');}</script>"
        redirect(url_for('showRestaurants'))
    if request.method == 'POST':
        if request.form['name']:
            editedRestaurant.name = request.form['name']
            return redirect(url_for('showRestaurants', restaurant_id=restaurant_id))
    else:
        return render_template(
            'editRestaurant.html', restaurant=editedRestaurant)


@app.route('/restaurants/<int:restaurant_id>/delete', methods=['GET', 'POST'])
def deleteRestaurant(restaurant_id):
    if 'username' not in login_session:
        return redirect('/login')
    restaurant = session.query(Restaurant).filter_by(id = restaurant_id).one()
    deleteRestaurant = session.query(
        Restaurant).filter_by(id=restaurant_id).one()
    if deleteRestaurant.user_id != login_session['user_id']:
        return "<script>\
        {alert('You are not authorized to delete this restaurant. \
        Please create your own restaurant.');}</script>"
        redirect(url_for('showRestaurants',restaurant_id=restaurant_id))
    if request.method == 'POST':
        session.delete(deleteRestaurant)
        session.commit()
        flash("Restaurant has been deleted!")
        return redirect(url_for(
            'showRestaurants',
            restaurant_id=restaurant_id)
            )
    else:
        return render_template(
            'deleterestaurant.html', restaurant=deleteRestaurant)


@app.route('/restaurants/<int:restaurant_id>/menu/')
def restaurantMenu(restaurant_id):
    restaurant = session.query(Restaurant).filter_by(id=restaurant_id).one()
    creator = getUserInfo(restaurant.user_id)
    items = session.query(MenuItem).filter_by(
        restaurant_id=restaurant_id).all()
    if 'username' not in login_session:
        return render_template(
            'publicmenu.html',
            items=items,
            restaurant=restaurant,
            creator=creator
            )
    else:
        return render_template(
            'menu.html',
            items=items,
            restaurant=restaurant,
            creator=creator
            )

# Task 1: Create route for newMenuItem function here


@app.route('/restaurants/<int:restaurant_id>/menu/new/', methods=['GET', 'POST'])
def newMenuItem(restaurant_id):
    if 'username' not in login_session:
        return redirect('/login')
    restaurant = session.query(Restaurant).filter_by(id=restaurant_id).one()
    if login_session['user_id'] != restaurant.user_id:
        return "<script>function myFunction()\
        {alert('You are not authorized to add menu items to this restaurant. \
        Please create your own restaurant in order to add items.');}</script><body onload='myFunction()''>"
        redirect(url_for('restaurantMenu', restaurant_id=restaurant_id))
    if request.method == 'POST':
        newItem = MenuItem(
            name=request.form['name'],
            description=request.form['description'],
            price=request.form['price'],
            course=request.form['course'],
            restaurant_id=restaurant_id,
            user_id=restaurant.user_id
            )
        session.add(newItem)
        session.commit()
        flash("New Menu %s Item Successfully Created" % (newItem.name))
        return redirect(url_for('restaurantMenu', restaurant_id=restaurant_id))
    else:
        return render_template('newmenuitem.html', restaurant_id=restaurant_id)

# Task 2: Create route for editMenuItem function here


@app.route(
            '/restaurants/<int:restaurant_id>/<int:menu_id>/edit/',
            methods=['GET', 'POST']
            )
def editMenuItem(restaurant_id, menu_id):
    if 'username' not in login_session:
        return redirect('/login')
    editedItem = session.query(MenuItem).filter_by(id = menu_id).one()
    restaurant = session.query(Restaurant).filter_by(id = restaurant_id).one()
    if login_session['user_id'] != restaurant.user_id:
        return "<script>\
        {alert('You are not authorized to edit menu items to this restaurant. \
        Please create your own restaurant in order to edit items.');}</script>"
        redirect(url_for('restaurantMenu', restaurant_id=restaurant_id))
    if request.method == 'POST':
        if request.form['name']:
            editedItem.name = request.form['name']
        if request.form['description']:
            editedItem.description = request.form['description']
        if request.form['price']:
            editedItem.price = request.form['price']
        if request.form['course']:
            editedItem.course = request.form['course']
        session.add(editedItem)
        session.commit()
        return redirect(url_for('restaurantMenu', restaurant_id=restaurant_id))
    else:
        return render_template(
            'editmenuitem.html',
            restaurant_id=restaurant_id,
            menu_id=menu_id,
            item=editedItem)

# Task 3: Create a route for deleteMenuItem function here


@app.route(
            '/restaurants/<int:restaurant_id>/menu/<int:menu_id>/delete',
            methods=['GET', 'POST']
            )
def deleteMenuItem(restaurant_id, menu_id):
    if 'username' not in login_session:
        return redirect('/login')
    itemToDelete = session.query(MenuItem).filter_by(id=menu_id).one()
    restaurant = session.query(Restaurant).filter_by(id = restaurant_id).one()
    if login_session['user_id'] != restaurant.user_id:
        return "<script>\
        {alert('You are not authorized to delete menu items to this restaurant. \
        Please create your own restaurant in order to delete items.');}</script>"
        redirect(url_for('restaurantMenu', restaurant_id=restaurant_id))
    if request.method == 'POST':
        session.delete(itemToDelete)
        session.commit()
        flash("item has been deleted!")
        return redirect(url_for('restaurantMenu', restaurant_id=restaurant_id))
    else:
        return render_template(
            'deleteMenuItem.html',
            restaurant_id=restaurant_id,
            menu_id=menu_id,
            item=itemToDelete
            )

def getUserID(email):
    try:
        user = session.query(User).filter_by(email=email).one_or_none()
        return user.id
    except:
        return None


def getUserInfo(user_id):
    user = session.query(User).filter_by(id=user_id).one_or_none()
    return user


def createUser(login_session):
    newUser = User(
        name=login_session['username'],
        email=login_session['email'],
        picture=login_session['picture'])
    session.add(newUser)
    session.commit()
    user = session.query(
        User
        ).filter_by(email=login_session['email']).one_or_none()
    return user.id

if __name__ == '__main__':
    # Should be in another file area
    app.secret_key = 'super_secret_key'
    app.debug = True
    app.run(host='0.0.0.0', port=5000)
