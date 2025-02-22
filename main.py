import discord
from discord import app_commands
from discord.ext import commands
import serial
import asyncio
from typing import Optional
import json
import os
from dotenv import load_dotenv

# Configuration file to store serial settings
CONFIG_FILE = 'serial_config.json'

# Default serial settings
DEFAULT_CONFIG = {
    'port': '/dev/ttyUSB0',  # Default port
    'baudrate': 9600,
    'bytesize': 8,
    'parity': 'N',
    'stopbits': 1,
    'timeout': 1,
    'encoding': 'utf-8',
    'encoding_errors': 'replace'
}

# Load or create config
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return DEFAULT_CONFIG.copy()

def save_config(config):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

class SerialBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()  # Enable all intents
        super().__init__(
            command_prefix='!',
            intents=intents,
            allowed_contexts=app_commands.AppCommandContext(guild=True,dm_channel=True,private_channel=True),
            allowed_installs=app_commands.AppInstallationType(guild=True,user=True)
        )
        
        self.serial_connection = None
        self.config = load_config()
        self.terminal_channels = set()

    async def setup_hook(self):
        await self.add_cog(SerialCog(self))
        print("Syncing commands...")
        try:
            # Sync commands globally instead of per-guild
            synced = await self.tree.sync(guild=None)
            print(f"Synced {len(synced)} command(s) globally")
        except Exception as e:
            print(f"Failed to sync commands: {e}")

class SerialCog(commands.Cog):
    def __init__(self, bot: SerialBot):
        self.bot = bot
        self.reading = False
        self.live_terminals = {}  # Store channel_id: message_id pairs for live terminals
        self.live_buffers = {}    # Store channel_id: buffer pairs for collecting responses
        self.update_task = None   # Task for updating live terminals
        
        # Update DM intent setting
        self.bot.intents.dm_messages = True

    @app_commands.command(name='connect')
    @app_commands.default_permissions(administrator=True)
    async def connect_serial(self, interaction: discord.Interaction):
        """Connect to the serial device with current settings"""
        try:
            if self.bot.serial_connection:
                await interaction.response.send_message("Already connected to serial device!")
                return

            self.bot.serial_connection = serial.Serial(
                port=self.bot.config['port'],
                baudrate=self.bot.config['baudrate'],
                bytesize=self.bot.config['bytesize'],
                parity=self.bot.config['parity'],
                stopbits=self.bot.config['stopbits'],
                timeout=self.bot.config['timeout'],
                xonxoff=False,     # Disable software flow control
                rtscts=False,      # Disable hardware flow control
                dsrdtr=False       # Disable hardware flow control
            )
            
            # Reset buffers
            self.bot.serial_connection.reset_input_buffer()
            self.bot.serial_connection.reset_output_buffer()
            
            await interaction.response.send_message(
                f"Connected to {self.bot.config['port']} at {self.bot.config['baudrate']} baud"
            )
        except Exception as e:
            await interaction.response.send_message(f"Error connecting to serial device: {str(e)}")

    @app_commands.command(name='disconnect')
    @app_commands.default_permissions(administrator=True)
    async def disconnect_serial(self, interaction: discord.Interaction):
        """Disconnect from the serial device"""
        if self.bot.serial_connection:
            self.bot.serial_connection.close()
            self.bot.serial_connection = None
            await interaction.response.send_message("Disconnected from serial device")
        else:
            await interaction.response.send_message("Not connected to any serial device")

    @app_commands.command(name='set')
    @app_commands.describe(
        parameter='The parameter to set (port, baudrate, bytesize, parity, stopbits)',
        value='The value to set for the parameter'
    )
    @app_commands.default_permissions(administrator=True)
    async def set_parameter(self, interaction: discord.Interaction, parameter: str, value: str):
        """Set serial parameters"""
        if parameter not in self.bot.config:
            await interaction.response.send_message(
                f"Invalid parameter. Available parameters: {', '.join(self.bot.config.keys())}"
            )
            return

        try:
            # Convert value to appropriate type
            if parameter == 'baudrate':
                value = int(value)
            elif parameter == 'bytesize':
                value = int(value)
            elif parameter == 'stopbits':
                value = float(value)
            
            self.bot.config[parameter] = value
            save_config(self.bot.config)
            await interaction.response.send_message(f"Set {parameter} to {value}")
        except ValueError:
            await interaction.response.send_message(f"Invalid value format for {parameter}")

    @app_commands.command(name='settings')
    async def show_settings(self, interaction: discord.Interaction):
        """Show current serial device settings"""
        settings = "\n".join([f"{k}: {v}" for k, v in self.bot.config.items()])
        await interaction.response.send_message(f"Current settings:\n```{settings}```")

    @app_commands.command(name='terminal')
    async def toggle_terminal(self, interaction: discord.Interaction):
        """Toggle terminal mode in the current channel"""
        if interaction.channel_id in self.bot.terminal_channels:
            self.bot.terminal_channels.remove(interaction.channel_id)
            await interaction.response.send_message("Terminal mode disabled in this channel")
        else:
            self.bot.terminal_channels.add(interaction.channel_id)
            await interaction.response.send_message("Terminal mode enabled in this channel")

    @app_commands.command(name='encoding')
    @app_commands.describe(
        encoding='The encoding to use (e.g., utf-8, ascii, latin1)',
        errors='How to handle encoding errors (strict, ignore, replace)'
    )
    async def set_encoding(self, interaction: discord.Interaction, encoding: str = 'utf-8', errors: str = 'replace'):
        """Set the encoding for serial communication"""
        try:
            # Test the encoding
            "test".encode(encoding)
            self.bot.config['encoding'] = encoding
            self.bot.config['encoding_errors'] = errors
            save_config(self.bot.config)
            await interaction.response.send_message(f"Set encoding to {encoding} with {errors} error handling")
        except LookupError:
            await interaction.response.send_message(f"Invalid encoding: {encoding}")

    @app_commands.command(name='flush')
    @app_commands.default_permissions(administrator=True)
    async def flush_buffers(self, interaction: discord.Interaction):
        """Flush serial port buffers"""
        if self.bot.serial_connection and self.bot.serial_connection.is_open:
            try:
                self.bot.serial_connection.reset_input_buffer()
                self.bot.serial_connection.reset_output_buffer()
                await interaction.response.send_message("Serial buffers flushed")
            except Exception as e:
                await interaction.response.send_message(f"Error flushing buffers: {str(e)}")
        else:
            await interaction.response.send_message("Not connected to serial device")

    @app_commands.command(name='liveterminal')
    @app_commands.default_permissions()  # Allow in DMs
    async def toggle_live_terminal(self, interaction: discord.Interaction):
        """Toggle live terminal mode in the current channel (updates single message)"""
        channel_id = interaction.channel_id
        
        if channel_id in self.live_terminals:
            # Disable live terminal
            try:
                channel = await self.bot.fetch_channel(channel_id)
                message = await channel.fetch_message(self.live_terminals[channel_id])
                await message.delete()
            except:
                pass  # Message might already be deleted
            
            del self.live_terminals[channel_id]
            del self.live_buffers[channel_id]
            
            await interaction.response.send_message("Live terminal mode disabled in this channel")
        else:
            # Enable live terminal
            await interaction.response.send_message("Live terminal mode enabled in this channel")
            
            # Create the terminal message
            channel = await self.bot.fetch_channel(channel_id)
            terminal_message = await channel.send("```\nWaiting for output...\n```")
            self.live_terminals[channel_id] = terminal_message.id
            self.live_buffers[channel_id] = []

    async def update_live_terminal_message(self, channel_id, content):
        """Helper function to update live terminal message"""
        try:
            # Try to get channel from different sources
            channel = self.bot.get_channel(channel_id)  # For server channels
            if not channel:
                # Try to get DM channel
                try:
                    channel = await self.bot.fetch_channel(channel_id)
                except discord.NotFound:
                    print(f"Could not find channel {channel_id} (neither server nor DM)")
                    return
                
            if not channel:
                print(f"Could not find channel {channel_id}")
                return
                
            try:
                message = await channel.fetch_message(self.live_terminals[channel_id])
                if not message:
                    print(f"Could not find message in channel {channel_id}")
                    return
                    
                # Only update if content has changed
                current_content = message.content.strip('```\n')
                if current_content != content:
                    print(f"Updating live terminal with new content: {content[:50]}...")  # Debug log
                    await message.edit(content=f"```\n{content}\n```")
                    
            except discord.NotFound:
                print(f"Message {self.live_terminals[channel_id]} not found in channel {channel_id}")
                # Remove invalid terminal
                if channel_id in self.live_terminals:
                    del self.live_terminals[channel_id]
                    del self.live_buffers[channel_id]
            except discord.HTTPException as e:
                print(f"HTTP error updating terminal: {e}")
            
        except Exception as e:
            print(f"Error updating live terminal: {e}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        channel_id = message.channel.id
        
        # Handle both regular and live terminal modes
        if channel_id in self.bot.terminal_channels or channel_id in self.live_terminals:
            if not message.content.startswith('/'):  # Ignore commands
                if self.bot.serial_connection and self.bot.serial_connection.is_open:
                    try:
                        print(f"Sending command: {message.content}")
                        temp_buffer = []
                        command = message.content.upper()  # Convert to uppercase for comparison
                        
                        # Determine timeout based on command
                        timeout = 15.0  # Default timeout
                        if "CWJAP" in command:  # WiFi connection commands
                            timeout = 45.0  # Longer timeout for WiFi operations
                        elif "CWLAP" in command:  # WiFi scan commands
                            timeout = 20.0  # Medium timeout for scanning
                        
                        # Send command
                        self.bot.serial_connection.write(f"{message.content}\r\n".encode())
                        self.bot.serial_connection.flush()
                        print(f"Command sent, waiting for response (timeout: {timeout}s)...")
                        
                        # Read and discard echo
                        echo = self.bot.serial_connection.readline()
                        print(f"Echo received: {echo}")
                        
                        # Initial update for live terminal
                        if channel_id in self.live_terminals:
                            await self.update_live_terminal_message(
                                channel_id,
                                f"Processing command (timeout: {timeout}s)..."
                            )
                        
                        await asyncio.sleep(0.5)
                        
                        # Read responses
                        start_time = asyncio.get_event_loop().time()
                        last_read_time = start_time
                        last_update_time = start_time
                        no_data_count = 0
                        
                        while (asyncio.get_event_loop().time() - start_time) < timeout:
                            current_time = asyncio.get_event_loop().time()
                            
                            # Update status every 5 seconds for long-running commands
                            if channel_id in self.live_terminals and (current_time - last_update_time) >= 5.0:
                                elapsed = int(current_time - start_time)
                                status = f"Command running for {elapsed}s...\n"
                                if temp_buffer:
                                    status += "\n".join(temp_buffer[-20:])
                                await self.update_live_terminal_message(channel_id, status)
                                last_update_time = current_time
                            
                            if self.bot.serial_connection.in_waiting:
                                print(f"Data available: {self.bot.serial_connection.in_waiting} bytes")
                                no_data_count = 0
                                
                                while self.bot.serial_connection.in_waiting:
                                    raw_response = self.bot.serial_connection.readline()
                                    print(f"Raw response: {raw_response}")
                                    
                                    try:
                                        response = raw_response.decode(
                                            self.bot.config['encoding'],
                                            errors=self.bot.config['encoding_errors']
                                        ).strip()
                                        print(f"Decoded response: {response}")
                                        
                                        if response and response != message.content:
                                            temp_buffer.append(response)
                                            # Update live terminal immediately
                                            if channel_id in self.live_terminals:
                                                print("Updating live terminal with new data")
                                                await self.update_live_terminal_message(
                                                    channel_id, 
                                                    "\n".join(temp_buffer[-20:])
                                                )
                                                # Force a small delay to prevent rate limiting
                                                await asyncio.sleep(0.1)
                                            
                                            # Check for completion indicators
                                            if response in ["OK", "FAIL", "ERROR"]:
                                                print(f"Command completed with status: {response}")
                                                no_data_count = 999  # Force exit
                                                break
                                            
                                    except UnicodeDecodeError as e:
                                        print(f"Decode error: {e}")
                                        hex_response = "Raw hex data: " + " ".join([f"{b:02x}" for b in raw_response])
                                        temp_buffer.append(hex_response)
                                
                                last_read_time = current_time
                            else:
                                await asyncio.sleep(0.1)
                                no_data_count += 1
                                
                                # Only exit if we've had no data for a while and received a completion indicator
                                if no_data_count > 20 and (current_time - last_read_time) > 2.0:
                                    if any(status in temp_buffer for status in ["OK", "FAIL", "ERROR"]):
                                        print("Command completed, no more data available")
                                        break
                                    elif (current_time - last_read_time) > 5.0:
                                        print("No data received for 5 seconds, continuing to wait...")
                                        no_data_count = 0  # Reset counter
                        
                        # Final update for both terminal modes
                        if temp_buffer:
                            joined_responses = "\n".join(temp_buffer)
                            
                            if channel_id in self.bot.terminal_channels:
                                await message.channel.send(f"```{joined_responses}```")
                            
                            if channel_id in self.live_terminals:
                                self.live_buffers[channel_id] = temp_buffer[-20:]
                                await self.update_live_terminal_message(
                                    channel_id,
                                    "\n".join(self.live_buffers[channel_id])
                                )
                        
                    except Exception as e:
                        error_msg = f"Error: {str(e)}"
                        print(f"Serial communication error: {error_msg}")
                        
                        if channel_id in self.bot.terminal_channels:
                            await message.channel.send(error_msg)
                        
                        if channel_id in self.live_terminals:
                            await self.update_live_terminal_message(channel_id, error_msg)
                else:
                    not_connected_msg = "Not connected to serial device"
                    
                    if channel_id in self.bot.terminal_channels:
                        await message.channel.send(not_connected_msg)
                    
                    if channel_id in self.live_terminals:
                        await self.update_live_terminal_message(channel_id, not_connected_msg)

# Bot token
load_dotenv()  # Load environment variables from .env file
TOKEN = os.getenv('DISCORD_TOKEN')

if not TOKEN:
    raise ValueError("No token found. Make sure DISCORD_TOKEN is set in your .env file")

# Create and run the bot
bot = SerialBot()

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    print(f'Bot ID: {bot.user.id}')
    print('------')

bot.run(TOKEN)
