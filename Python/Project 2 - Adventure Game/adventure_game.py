# This script implements a simple text-based adventure game where players make choices to explore different scenarios.

print("Adventure game setup confirmed!")

def start_game():
    """
    Starts the adventure game by displaying an introduction,
    asking for the player's name, and providing an initial choice.
    """
    print("Welcome to the Adventure Game!")
    print("In this game, you will embark on an exciting journey filled with choices and challenges.")
    
    # Ask for the player's name
    player_name = input("What is your name, brave adventurer? ")
    
    print(f"Hello, {player_name}! Your adventure begins now.\n")
    
    # Provide initial choice
    print("\nYou find yourself at a crossroads in a mysterious land.")
    print("To your left, a dark forest beckons with unknown dangers and treasures.")
    print("To your right, a shadowy cave entrance promises hidden secrets.")
    
    choice = input("Do you want to explore the forest or enter the cave? (forest/cave): ").lower()
    
    if choice == "forest":
        print(f"\n{player_name}, you venture into the forest. The trees whisper ancient secrets...")
        forest_path()  # Call the function to handle the forest path
    elif choice == "cave":
        print(f"\n{player_name}, you cautiously enter the cave. Echoes of dripping water surround you...")
        cave_path()  # Call the function to handle the cave path
    else:
        print(f"\n{player_name}, that's not a valid choice. The crossroads fade away, and you must start over.")
        start_game()  # Recursive call to restart if invalid choice

def forest_path():
    """
    This function can be expanded to include the storyline and choices for the forest path.
    """
    print("As you walk through the forest, you encounter a mysterious creature. It offers you a riddle to solve in exchange for a treasure.")
    # Expand this function with more choices and outcomes based on the player's decisions in the forest.
    # Ask the player to choose between following a river or climbing a tree, and then provide different scenarios based on their choice.
    
    print("Do you want to follow the river or climb a tree? (river/tree): ")
    choice = input().lower()
    if choice == "river":
        print("You follow the river and discover a hidden waterfall with a treasure chest behind it!")
        # Add more logic for what happens when they find the treasure
    elif choice == "tree":
        print("You climb the tree and find a nest with a magical egg inside!")
        # Add more logic for what happens when they find the magical egg
    else:
        print("That's not a valid choice. The forest path fades away, and you must start over.")
        start_game()  # Recursive call to restart if invalid choice           

def cave_path():
    """
    This function can be expanded to include the storyline and choices for the cave path.
    """
    print("As you explore the cave, you find a hidden chamber filled with ancient artifacts. A guardian spirit appears and offers you a challenge.")
    # Expand this function with more choices and outcomes based on the player's decisions in the cave.
    # Ask the player to choose between light a torch or proceed in the dark, and then provide different scenarios based on their choice.
    
    print("Do you want to light a torch or proceed in the dark? (torch/proceed): ")
    choice = input().lower()
    if choice == "proceed":
        print("You solve the puzzle and unlock a secret passage that leads to a treasure room!")
        # Add more logic for what happens when they find the treasure
    elif choice == "torch":
        print("You light the torch and navigate through the cave, discovering a hidden treasure!")
        # Add more logic for what happens when they find the treasure
    else:
        print("That's not a valid choice. The cave path fades away, and you must start over.")
        start_game()  # Recursive call to restart if invalid choice

# Note: To start the game, call start_game() at the end of the script or in an interactive session

start_game()