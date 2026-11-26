"""Ground truth for the six houses of the user's reference pack, written by a person (Claude) looking at each finished image.

Values may be a list of acceptable alternatives where the picture is genuinely ambiguous (e.g. a door between centre and left).
"""

TRUTH: dict[str, dict] = {
    "01_terrea_bege_varanda": dict(floors=1, roof_type="gable", roof_color="dark_green", wall_material="siding", wall_color="beige",
                                   lower_wall_material="none", trim_color="cream", door_color="orange", door_position="center",
                                   windows_front_per_floor=[2], porch="covered_porch", garage=False, chimney=False, volumes="single", bay_window=False),
    "02_sobrado_azul": dict(floors=2, roof_type="hip", roof_color="dark_gray", wall_material="siding", wall_color="blue",
                            lower_wall_material="none", trim_color="cream", door_color="orange", door_position=["center", "left"],
                            windows_front_per_floor=[1, 2], porch="portico", garage=False, chimney=False, volumes="single", bay_window=False),
    "03_casa_amarela_meios_niveis": dict(floors=2, roof_type=["gable", "hip"], roof_color="dark_gray", wall_material="siding", wall_color="yellow",
                                         lower_wall_material="brick", lower_wall_color="brick_red", trim_color="cream", door_color="orange",
                                         door_position="center", windows_front_per_floor=[2, 1], porch="none", garage=False, chimney=False,
                                         volumes="stepped", bay_window=False),
    "04_casa_moderna_telhado_inclinado": dict(floors=1, roof_type="shed", roof_color="dark_gray", wall_material="stucco", wall_color="beige",
                                              lower_wall_material="none", trim_color=["black", "dark_gray"], door_color="orange",
                                              door_position=["left", "center"], windows_front_per_floor=[2], porch="small_roof", garage=False,
                                              chimney=False, volumes="stepped", bay_window=False),
    "05_sobrado_tijolo_aparente": dict(floors=2, roof_type="hip", roof_color="dark_gray", wall_material="brick", wall_color="brick_red",
                                       lower_wall_material="none", trim_color="cream", door_color="orange", door_position=["center", "right"],
                                       windows_front_per_floor=[1, 2], porch="portico", garage=False, chimney=False, volumes="single", bay_window=True),
    "06_sobrado_verde_garagem": dict(floors=2, roof_type="gable", roof_color="dark_gray", wall_material="siding", wall_color="sage_green",
                                     lower_wall_material="none", trim_color="cream", door_color="orange", door_position=["center", "left"],
                                     windows_front_per_floor=[2, 2], porch="covered_porch", garage=True, garage_side="right", chimney=False,
                                     volumes="with_side_wing", bay_window=False),
}
