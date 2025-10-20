For this project I set up with 5 files (db, utils, auth, foods, and app)
In the db file, it creates the SQLite database to store persistent user data and information.
In the utils file, I created several tools that allow users to input all necessary information before processing their data, such as personal profiles, daily records, and water intake. This tool is providing users some personal recommendation for daily goal.
In the auth file, I set up to handle user authentication and verify login credentials.
In foods file, which help user to generate the recommend food based on the data they upload.
For the most part, the app file runs the user interface and integrates all the functions I created earlier. My web app generates a chart showing users’ daily water intake progress, helping them track how much water remains to reach their daily goal. When users input their daily records for a specific date, the app generates a dot chart to visualize weight progress and a pie chart showing the average proportions of protein, carbohydrates, and fat. Lastly, the food recommendation feature assists users in making informed meal choices. If they don't have any thought of pick up the food, they can upload their data to generate it.

My goal for this app is to support users who are busy with their academic or work. This tool helps them save time by automatically generating daily goals and reducing the need to manually enter data into spreadsheets.

Although I placed all the files separately in this dashboard, I also created the healthylife_app package, which includes the default file for food recommendations, making it easier to download all the files to save time.

When run the code: just download the package and pop up the terminal and type the "streamlit run app.py".
