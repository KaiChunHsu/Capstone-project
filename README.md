For this project I set up with 5 files (db, utils, auth, foods, and app)
In db file which just create the SQLite file to store persistence users' data/info
In utils file, I create lots of tool for user to put all the information before running the data, such as personal file, daily record, water inatke. These resource is providing users some recommendation for their daily goal of nutrition&water intake. 
In auth file, I set up this for checking user authentication.
In foods file, which help user to generate the recommend food based on the data they upload.
For the most of the part, the app file which run the UI and generate all the function I create through the process I just made before. My web app will generate the chart for the daily water progress which could remind how much water left for their daily goal. Also, when users input their daily record for specific date, it will generate the dot chart for weight progress, and pie chart for mean of protein, carbs, and fat. Last but not least for my food recommendation function, it will help users to make the decision of meal choice. If they don't have any thought of pick up the food, they can upload their data to generate the foods.

My goal for this app is providing the users who is busy on their academic/work. This opportunity is going to help them reduce their time to put the data on the sheet and auto generate the daily goal.

Run the termianl to generate my web app is: type the file name (I recommend use healthylife_app to set the name file) and run with streamlit run app.py and it will generate the website.
