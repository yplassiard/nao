#Nao (NVDA Advanced OCR) is an addon that improves the standard OCR capabilities that NVDA provides on modern Windows versions.
#This file is covered by the GNU General Public License.
#See the file COPYING for more details.
# 2021-12-08, added script decorator and category for two main keys.
# 2021-12-11, fixed file extension check.
# 2021-12-14, xplorer2 support
#Last update 2021-12-14
#Copyright (C) 2021 Alessandro Albano, Davide De Carne and Simone Dal Maso

import globalPluginHandler
import os
import ui
import winVersion
import vision
import api
import threading
import subprocess
import nvwave
import speech
import addonHandler
import logHandler
from comtypes.client import CreateObject as COMCreate
from .OCREnhance import recogUiEnhance, beepThread, totalCommanderHelper, xplorer2Helper, twain
from .OCREnhance.recogUiEnhance import queue_ui_message
from visionEnhancementProviders.screenCurtain import ScreenCurtainProvider
from contentRecog import recogUi
from scriptHandler import script

addonHandler.initTranslation()

# Global variables
filePath = ""
fileExtension = ""
suppFiles = ["pdf", "bmp", "pnm", "pbm", "pgm", "png", "jpg", "jp2", "gif", "tif", "jfif", "jpeg", "tiff", "spix", "webp"]
addonPath = os.path.dirname(__file__)
pdfToPngToolPath = "\""+os.path.join (addonPath, "tools", "pdftopng.exe")+"\""
webpToPngToolPath = "\""+os.path.join (addonPath, "tools", "dwebp.exe")+"\""
pdfToImagePath = "" + os.path.join (addonPath, "images") + ""
pdfToImageFileNamePath = pdfToImagePath + "\\img"

ADDON_SUMMARY = addonHandler.getCodeAddon().manifest["summary"]


class TwainThread(threading.Thread):
        def run(self):
                ret = None
                
                try:
                        ret = twain.acquire(os.path.join(os.getenv("USERPROFILE"), "Desktop", "image.jpg"),
                                            pixel_type='gray',
                                            parent_window=api.getFocusObject().windowHandle,
                                            show_ui=True)
                except Exception as ex:
                        logHandler.log.exception("Failed to acquire image: {why}".format(why=ex))
                        ret = None
                if ret is None:
                        queue_ui_message("Cancelled")
                else:
                        logHandler.log.info("We got an image {data}".format(data=ret))
        


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	scriptCategory = ADDON_SUMMARY
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.recogUiEnhance = recogUiEnhance.RecogUiEnhance()
		self.beeper = beepThread.BeepThread()


	@script(
		# Translators: Message presented in input help mode.
		description=_("Take a full screen shot and recognize it."),
		gesture="kb:NVDA+shift+control+R"
	)
	def script_doRecognizeScreenshotObject(self, gesture):
		if not winVersion.isUwpOcrAvailable():
			# Translators: Reported when Windows OCR is not available.
			ui.message(_("Windows OCR not available"))
			return
		screenCurtainId = ScreenCurtainProvider.getSettings().getId()
		screenCurtainProviderInfo = vision.handler.getProviderInfo(screenCurtainId)
		isScreenCurtainRunning = bool(vision.handler.getProviderInstance(screenCurtainProviderInfo))
		if isScreenCurtainRunning:
			# Translators: Reported when screen curtain is enabled.
			ui.message(_("Please disable screen curtain before using Windows OCR."))
			return
		self.recogUiEnhance.recognizeScreenshotObject()

	@script(
		# Translators: Message presented in input help mode.
		description=_("Recognize the content of the selected image or PDF file."),
		gesture="kb:NVDA+shift+r"
	)
	def script_doRecognizeFileObject(self, gesture):
		if not winVersion.isUwpOcrAvailable():
			# Translators: Reported when Windows OCR is not available.
			ui.message(_("Windows OCR not available"))
			return
			
		p = self.getFilePath()
		if p == True:
			if fileExtension == 'pdf':
				self.convertPdfToPng()
			elif fileExtension == 'webp':
				self.convertWebPtoPng()
			else:
				ui.message(_("Process started"))
				self.recogUiEnhance.recognizeImageFileObject(filePath)
		else:
			pass
	@script(
		# Translators: Message presented in input help mode.
		description=_("Recognize content from scanner."),
		gesture="kb:NVDA+shift+space"
	)
	def script_doRecognizeFromTwainScanner(self, gesture):
                t = TwainThread()
                t.start()
	def getFilePath(self): #For this method thanks to some nvda addon developers ( code snippets and suggestion)
		global filePath
		global fileExtension
		
		# We check if we are in the xplorer2
		xplorer2 = xplorer2Helper.Xplorer2Helper()
		if xplorer2.is_valid():
			filePath = xplorer2.currentFileWithPath()
			if not filePath:
				return False
		else:
			# We check if we are in the Total Commander
			tcmd = totalCommanderHelper.TotalCommanderHelper()
			if tcmd.is_valid():
				filePath = tcmd.currentFileWithPath()
				if not filePath:
					return False
			else:
				# We check if we are in the Windows Explorer.
				fg = api.getForegroundObject()
				if (fg.role != api.controlTypes.Role.PANE and fg.role != api.controlTypes.Role.WINDOW) or fg.appModule.appName != "explorer":
					ui.message(_("You must be in a Windows File Explorer window"))
					return False
				
				self.shell = COMCreate("shell.application")
				desktop = False
				# We go through the list of open Windows Explorers to find the one that has the focus.
				for window in self.shell.Windows():
					if window.hwnd == fg.windowHandle:
						focusedItem=window.Document.FocusedItem
						break
				else: # loop exhausted
					desktop = True
				# Now that we have the current folder, we can explore the SelectedItems collection.
				if desktop:
					desktopPath = desktop = os.path.join(os.path.join(os.environ['USERPROFILE']), 'Desktop')
					fileName = api.getDesktopObject().objectWithFocus().name
					filePath = desktopPath + '\\' + fileName
				else:
					filePath = str(focusedItem.path)
		
		# Getting the extension to check if is a supported file type.
		fileExtension = os.path.splitext(filePath)[1].lower()
		if fileExtension and fileExtension.startswith('.'):
			fileExtension = fileExtension[1:]
		if fileExtension and fileExtension in suppFiles:
			return True # Is a supported file format, so we can make OCR
		else:
			ui.message(_("File not supported"))
			return False # It is a file format not supported so end the process.

	def convertPdfToPng(self):
		if isinstance(api.getFocusObject(), recogUi.RecogResultNVDAObject):
			# Translators: Reported when content recognition (e.g. OCR) is attempted,
			# but the user is already reading a content recognition result.
			ui.message(_("Already in a content recognition result"))
			return
		
		self._thread = threading.Thread(target = self._pdfToPngThread)
		self._thread.setDaemon(True)
		self._thread.start()

	def convertWebPtoPng(self):
		if isinstance(api.getFocusObject(), recogUi.RecogResultNVDAObject):
			# Translators: Reported when content recognition (e.g. OCR) is attempted,
			# but the user is already reading a content recognition result.
			ui.message(_("Already in a content recognition result"))
			return
		
		self._thread = threading.Thread(target = self._webpToPngThread)
		self._thread.setDaemon(True)
		self._thread.start()

	def _pdfToPngThread(self):
		# The next two lines are to prevent the cmd from being displayed.
		si = subprocess.STARTUPINFO()
		si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
		try:
			for f in os.listdir(pdfToImagePath):
				os.remove(os.path.join(pdfToImagePath, f))
		except FileNotFoundError:
			queue_ui_message(_("Error, file not found"))
			pass
		command = "{} \"{}\" \"{}\"".format(pdfToPngToolPath, filePath, pdfToImageFileNamePath)
		
		queue_ui_message(_("Process started"))
		self.beeper.start()
		p = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=si)
		stdout, stderr = p.communicate()
		
		if p.returncode == 0:
			self.recogUiEnhance.recognizePdfFileObject(os.listdir(pdfToImagePath), pdfToImagePath, self._pdfToPngFinish)
		else:
			queue_ui_message(_("Error, the file could not be processed."))
			self.beeper.stop()

	def _pdfToPngFinish(self):
		self.beeper.stop()
		speech.cancelSpeech()
		try:
			for f in os.listdir(pdfToImagePath):
				os.remove(os.path.join(pdfToImagePath, f))
		except FileNotFoundError:
			pass

	def _webpToPngThread(self):
		# The next two lines are to prevent the cmd from being displayed.
		si = subprocess.STARTUPINFO()
		si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
		try:
			for f in os.listdir(pdfToImagePath):
				os.remove(os.path.join(pdfToImagePath, f))
		except FileNotFoundError:
			queue_ui_message(_("Error, file not found"))
			pass
		command = "{} \"{}\" -o \"{}\\{}.png\"".format(webpToPngToolPath, filePath, pdfToImagePath, os.path.basename(filePath))
		print(command)
		
		queue_ui_message(_("Process started"))
		self.beeper.start()
		p = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=si)
		stdout, stderr = p.communicate()
		
		if p.returncode == 0:
			self.recogUiEnhance.recognizeImageFileObject("{}\\{}.png".format(pdfToImagePath, os.path.basename(filePath)))
			try:
				for f in os.listdir(pdfToImagePath):
					os.remove(os.path.join(pdfToImagePath, f))
			except FileNotFoundError:
				pass
		else:
			queue_ui_message(_("Error, the file could not be processed."))
		self.beeper.stop()
