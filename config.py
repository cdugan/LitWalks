"""Project-wide configuration.

Defines the default bounding box `BBOX` used across the app.
Format: (north, south, east, west)
"""

# Medium size area (Hendersonville region)
# BBOX = (35.42, 35.28, -82.40, -82.55) 
# smaller Hendersonville area for testing
# BBOX = (35.322, 35.31, -82.45, -82.47) 

# Raleigh downtown small
# 35.776714, -78.649396 to 35.787430, -78.634265
BBOX = (35.78743, 35.77671, -78.63426, -78.64940)

# Raleigh downtown larger
# 35.794546, -78.685192 to 35.769167, -78.616052
# BBOX = (35.794546, 35.769167, -78.616052, -78.685192)
# Raleigh area smalls
# BBOX = (35.75, 35.72, -78.72, -78.75)
# Raleigh area large
# BBOX = (36.043, 35.617, -78.425, -79.129) # (too big - causes crashing)

# Delta Electronics area
#$$c(W 78°57'33"--W 78°46'25"/N 35°56'44"--N 35°47'22")
# BBOX = (35.92, 35.83, -78.83, -78.92)