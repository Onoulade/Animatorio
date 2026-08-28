local recipe_name = "animatorio-animation-validation"
local entities = {
  {name = "mechanical-printer", position = {-18, -15}},
  {name = "printer-t1", position = {-12, -15}},
  {name = "printer-t2", position = {-6, -15}},
  {name = "chromatic-printer", position = {0, -15}},
  {name = "laser-printer", position = {6, -15}},
  {name = "fax-emitter", position = {12, -15}},
  {name = "interplanetary-fax-exchange", position = {18, -15}},

  {name = "notary-office", position = {-18, -5}},
  {name = "conciliation-desk", position = {-12, -5}},
  {name = "digital-services-bureau", position = {-6, -5}},
  {name = "administrative-space-station", position = {0, -5}},
  {name = "corporate-breakroom", position = {7, -5}},
  {name = "formation-center", position = {16, -5}},

  {name = "union-headquarters", position = {-14, 8}},
  {name = "territorial-arbitration-post", position = {-3, 8}},
  {name = "biter-station", position = {8, 8}},
  {name = "biterport", position = {17, 8}},
}

local function prepare_surface()
  local surface = game.surfaces.nauvis or game.surfaces[1]
  surface.freeze_daytime = true
  surface.daytime = 0
  for _, player in pairs(game.players) do
    player.teleport({80, 80}, surface)
  end
  for _, entity in pairs(surface.find_entities_filtered({area = {{-28, -24}, {28, 20}}})) do
    if entity.valid and entity.type ~= "character" then entity.destroy() end
  end
  surface.destroy_decoratives({area = {{-28, -24}, {28, 20}}})

  local tiles = {}
  for x = -28, 28 do
    for y = -24, 20 do
      tiles[#tiles + 1] = {name = "grass-1", position = {x, y}}
    end
  end
  surface.set_tiles(tiles)

  for _, spec in ipairs(entities) do
    local entity = surface.create_entity({
      name = spec.name,
      position = spec.position,
      force = "player",
      create_build_effect_smoke = false,
    })
    if not entity then error("Failed to create " .. spec.name) end
    if entity.type == "assembling-machine" then
      entity.set_recipe(recipe_name)
    end
  end
  return surface
end

local function screenshot(surface, suffix)
  for _, spec in ipairs(entities) do
    game.take_screenshot({
      surface = surface,
      position = spec.position,
      resolution = {512, 384},
      zoom = 2,
      path = "animatorio-animation-" .. suffix .. "-" .. spec.name .. ".png",
      show_gui = false,
      show_entity_info = false,
      anti_alias = true,
    })
  end
  game.take_screenshot({
    surface = surface,
    position = {0, -1},
    resolution = {1920, 1200},
    zoom = 0.9,
    path = "animatorio-animation-" .. suffix .. ".png",
    show_gui = false,
    show_entity_info = false,
    anti_alias = true,
  })
end

script.on_init(function()
  if remote.interfaces.freeplay then
    remote.call("freeplay", "set_skip_intro", true)
    remote.call("freeplay", "set_disable_crashsite", true)
  end
  storage.animatorio_animation_validation_surface = prepare_surface()
end)

script.on_event(defines.events.on_tick, function(event)
  local surface = storage.animatorio_animation_validation_surface
  if not surface then return end
  if event.tick == 45 then
    screenshot(surface, "phase-a")
  elseif event.tick == 75 then
    screenshot(surface, "phase-b")
  elseif event.tick == 90 then
    storage.animatorio_animation_validation_surface = nil
  end
end)
